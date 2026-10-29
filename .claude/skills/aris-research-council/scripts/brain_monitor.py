"""Independent stdlib-only BrainDance monitor (Python 3.9+).

Normal checks use no models or SSH. Recovery uses the existing guarded backend.
The LaunchAgent runs one bounded check per minute, rather than an LLM heartbeat.
"""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import html
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import sqlite3
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime,timezone

INTERVAL=60
STALL_SECONDS=900
MAX_LOG_BYTES=512*1024


def stamp():return datetime.now(timezone.utc).isoformat()
def epoch(value):
    try:return datetime.fromisoformat(value.replace('Z','+00:00')).timestamp()
    except (ValueError,AttributeError,TypeError):return 0
def read(path,default=None):return json.loads(path.read_text()) if path.is_file() else (default if default is not None else {})
def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd,name=tempfile.mkstemp(prefix='.monitor-',dir=str(path.parent));os.fchmod(fd,0o600)
    try:
        with os.fdopen(fd,'w') as stream:json.dump(value,stream,ensure_ascii=False)
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)
@contextmanager
def connect(path):
    c=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=1);c.row_factory=sqlite3.Row
    try:yield c
    finally:c.close()
def label(db):return 'com.braindance.monitor.'+hashlib.sha256(str(db).encode()).hexdigest()[:8]
def agent_path(db):return Path.home()/'Library/LaunchAgents'/(label(db)+'.plist')
def valid_server(server):
    u=urllib.parse.urlsplit(server)
    if u.scheme!='http' or u.hostname not in {'127.0.0.1','localhost'} or u.username or u.password or u.path not in {'','/'} or u.query or u.fragment:raise ValueError('감시 대상은 로컬 BrainDance 주소만 지정하세요.')
    return server.rstrip('/')
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None
def health(server,db):
    try:
        with urllib.request.build_opener(NoRedirect()).open(server+'/api/health',timeout=3) as r:v=json.load(r)
        return v.get('app')=='BrainDance' and v.get('workspace_id')==hashlib.sha256(str(db).encode()).hexdigest()
    except (OSError,ValueError):return False


def error_kind(text):
    text=text.lower()
    for words,kind in [(['timed out','timeouterror','시간 초과'],'timeout'),(['429','rate_limit'],'rate-limit'),(['no module named'],'missing-dependency'),(['영수증이 없습니다','receipt missing'],'missing-receipt'),(['unauthorized','authentication','로그인'],'authentication')]:
        if any(w in text for w in words):return kind
    return 'tool-error'
def log_events(path,cursor):
    """Read new bounded JSONL only. Tool heartbeats/output size are not progress."""
    if not path.is_file() or path.is_symlink():return []
    stat=path.stat()
    if not cursor:
        cursor.update(inode=stat.st_ino,offset=stat.st_size,success=None);return []
    if cursor.get('inode')!=stat.st_ino or cursor.get('offset',0)>stat.st_size:cursor.update(inode=stat.st_ino,offset=0,skip=False,success=None)
    with path.open('rb') as f:f.seek(cursor['offset']);chunk=f.read(MAX_LOG_BYTES)
    end=chunk.rfind(b'\n')
    if end<0:
        if len(chunk)==MAX_LOG_BYTES:cursor.update(offset=cursor['offset']+len(chunk),skip=True)
        return []
    lines=chunk[:end].splitlines();cursor['offset']+=end+1
    if cursor.pop('skip',False):lines=lines[1:]
    errors=[]
    for line in lines:
        try:row=json.loads(line)
        except (ValueError,UnicodeDecodeError):continue
        if not isinstance(row,dict) or not isinstance(row.get('message'),dict):continue
        blocks=row['message'].get('content',[])
        if not isinstance(blocks,list):continue
        for block in blocks:
            if not isinstance(block,dict) or block.get('type')!='tool_result':continue
            content=block.get('content','')
            if isinstance(content,list):content='\n'.join(b.get('text','') for b in content if isinstance(b,dict) and b.get('type')=='text')
            content=str(content).lstrip();identity=block.get('tool_use_id') or hashlib.sha256(line).hexdigest()
            if block.get('is_error') or content.startswith('Command [') and 'timed out after ' in content[:3000] or content.startswith('<tool_use_error>'):errors.append((identity,error_kind(content)))
            else:cursor['success']=identity
    return errors


def inspect(db,server,state,clock,probe=health):
    findings={};active=set();state.setdefault('sessions',{})
    with connect(db) as c:
        sessions=[dict(r) for r in c.execute("SELECT a.*,p.title FROM automatic_sessions a JOIN projects p ON p.id=a.project_id LEFT JOIN project_lifecycle l ON l.project_id=p.id WHERE a.status='running' AND l.deleted_at IS NULL")]
        sessions=[s for s in sessions if json.loads(s['config']).get('deadline_epoch',clock+1)>clock]
        for s in sessions:
            active.add(s['id']);watch=state['sessions'].setdefault(s['id'],dict(started=clock,since=clock,jobs={},errors=[]))
            jobs=[dict(r) for r in c.execute('SELECT id,state,phase,message,error,run_dir,updated_at FROM research_jobs WHERE project_id=? ORDER BY rowid DESC LIMIT 16',(s['project_id'],))]
            runs=[dict(r) for r in c.execute("SELECT id,state,started_at,timeout_seconds FROM experiment_runs WHERE project_id=? AND state IN ('queued','running')",(s['project_id'],))]
            watch['errors']=[e for e in watch['errors'] if e['at']>clock-1800][-64:];marks=[];valid_jobs=set()
            for job in jobs:
                valid_jobs.add(job['id']);cursor=watch['jobs'].setdefault(job['id'],{})
                folder=Path(job['run_dir']).resolve();owned=folder.parent==db.parent/'council-runs'
                if owned and job['state'] in {'queued','running'}:
                    for identity,kind in log_events(folder/'native.stdout.jsonl',cursor):watch['errors'].append(dict(id=identity,job=job['id'],kind=kind,at=clock))
                    marks.append([job['id'],job['state'],job['phase'],job['message'],cursor.get('success')])
                if job['state']=='failed' and job['error'] and epoch(job['updated_at'])>=watch['started'] and not cursor.get('failure_seen'):
                    if not any(e['job']==job['id'] for e in watch['errors']):watch['errors'].append(dict(id=job['id'],job=job['id'],kind=error_kind(job['error']),at=clock))
                    cursor['failure_seen']=True
            watch['jobs']={k:v for k,v in watch['jobs'].items() if k in valid_jobs}
            progress=json.loads(s['progress']);fingerprint=hashlib.sha256(json.dumps([progress.get('phase'),progress.get('native_cycle'),marks,[[r['id'],r['state']] for r in runs]],sort_keys=True).encode()).hexdigest()
            if fingerprint!=watch.get('fingerprint'):watch.update(fingerprint=fingerprint,since=clock)
            phase=marks[0][2] if marks else progress.get('phase','unknown')
            def finding(kind,message,key=None):
                findings[key or s['id']+':'+kind]=dict(session=s['id'],project=s['project_id'],title=s['title'],kind=kind,phase=phase,message=message)
            long_run=False
            for run in runs:
                elapsed=clock-epoch(run['started_at']) if run['started_at'] else 0
                if run['state']=='running' and run['started_at']:
                    if elapsed>run['timeout_seconds']+120:finding('experiment-overdue','실험 실행 기록이 검토된 제한 시간과 종료 정리 유예를 넘었습니다.',run['id']+':overdue')
                    else:long_run=True
            if not long_run and clock-watch['since']>=STALL_SECONDS:finding('stalled','15분 이상 단계 변경이나 새 도구 처리 결과가 없습니다. 정체 의심이며 자동 재시작하지 않았습니다.')
            for kind in {e['kind'] for e in watch['errors']}:
                items={e['id']:e for e in watch['errors'] if e['kind']==kind}
                if len(items)>=3 and max(e['at'] for e in items.values())>clock-300:finding('repeated-'+kind,'최근 30분에 같은 종류의 오류가 '+str(len(items))+'회 발생했습니다: '+kind)
    state['sessions']={k:v for k,v in state['sessions'].items() if k in active}
    healthy=probe(server,db);state['backend_failures']=0 if healthy else state.get('backend_failures',0)+1
    if active and state['backend_failures']>=3:findings['backend-down']=dict(session=None,title='BrainDance',kind='backend-down',phase='backend',message='실행 중인 연구가 있지만 로컬 백엔드 응답을 3회 연속 확인하지 못했습니다. 연구를 새로 시작하지 않았습니다.')
    return findings,active,healthy


def slack_target(db):
    path=db.parent/'integrations/slack-credentials.json';settings=db.parent/'integrations/slack.sqlite3'
    if not path.is_file() or not settings.is_file():return {}
    with connect(settings) as c:row=c.execute('SELECT enabled FROM notification_settings WHERE id=1').fetchone()
    if not row or not row[0]:return {}
    v=read(path)
    if not re.fullmatch(r'xoxb-[A-Za-z0-9-]{10,1000}',v.get('token','')) or not re.fullmatch(r'D[A-Z0-9]{8,24}',v.get('channel','')):return {}
    return v
def target_id(target):return hashlib.sha256(json.dumps([target.get(k) for k in ['team_id','member_id','channel']]).encode()).hexdigest()
def post(target,text,cafile):
    payload=dict(channel=target['channel'],text=text,unfurl_links=False,unfurl_media=False)
    req=urllib.request.Request('https://slack.com/api/chat.postMessage',data=json.dumps(payload).encode(),headers={'Authorization':'Bearer '+target['token'],'Content-Type':'application/json; charset=utf-8'})
    context=ssl.create_default_context(cafile=str(cafile) if cafile.is_file() else None)
    try:
        opener=urllib.request.build_opener(NoRedirect(),urllib.request.HTTPSHandler(context=context))
        with opener.open(req,timeout=10) as r:result=json.load(r)
        return ('sent',0) if isinstance(result,dict) and result.get('ok') else ('failed',0)
    except urllib.error.HTTPError as e:
        if e.code==429:
            try:return 'pending',min(3600,max(1,float(e.headers.get('Retry-After','60'))))
            except ValueError:return 'pending',60
        return ('uncertain',0) if e.code>=500 else ('failed',0)
    except (OSError,ValueError):return 'uncertain',0


def register_runtime(db,server):
    db=Path(db).resolve();image=Path(sys.executable).resolve()
    save(db.parent/'monitor/backend-runtime.json',dict(db=str(db),server=valid_server(server),pid=os.getpid(),image=str(image),sha256=hashlib.sha256(image.read_bytes()).hexdigest(),frozen=bool(getattr(sys,'frozen',False))))


def restart_backend(db,server):
    """Restart only the registered immutable image after checked experiment limits."""
    entry=read(db.parent/'monitor/backend-runtime.json')
    if entry.get('db')!=str(db) or entry.get('server')!=server or not entry.get('frozen'):return dict(state='no_registered_runtime')
    image=Path(entry['image']);base=db.parent/'runtime-binaries'
    if image.is_symlink() or image.parent.parent!=base or image.name!='BrainDanceServer' or image.parent.name!=entry.get('sha256') or hashlib.sha256(image.read_bytes()).hexdigest()!=entry['sha256']:return dict(state='invalid_runtime')
    # An unavailable API can coexist with an active SSH worker: do not orphan it.
    with connect(db) as c:
        rows=c.execute("SELECT started_at,timeout_seconds FROM experiment_runs WHERE state='running'").fetchall()
        if any(not r['started_at'] or time.time()<epoch(r['started_at'])+r['timeout_seconds']+120 for r in rows):return dict(state='waiting_for_experiment')
        configs=[json.loads(r[0]) for r in c.execute("SELECT config FROM automatic_sessions WHERE status='running'")]
        if not any(v.get('deadline_epoch',time.time()+1)>time.time() and not read(Path(v['session_budget'])).get('quota_stop') for v in configs):return dict(state='no_authorized_research')
    try:
        os.kill(entry['pid'],0)
        command=subprocess.run(['/bin/ps','-p',str(entry['pid']),'-o','command='],capture_output=True,text=True,timeout=2).stdout.strip()
        if not command.startswith(str(image)+' --db '+str(db)+' --port '):return dict(state='process_identity_mismatch')
        import signal
        os.kill(entry['pid'],signal.SIGTERM)  # Graceful shutdown owns worker cleanup.
        for _ in range(20):
            try:os.kill(entry['pid'],0)
            except ProcessLookupError:break
            time.sleep(.2)
        else:return dict(state='backend_stopping')
    except ProcessLookupError:pass
    import socket
    u=urllib.parse.urlsplit(server)
    with socket.socket() as sock:
        sock.settimeout(.3)
        if sock.connect_ex((u.hostname,u.port or 80))==0:return dict(state='port_owned_by_other_process')
    with (db.parent/'cli-backend.log').open('ab') as log:
        env=os.environ.copy();env['PYINSTALLER_RESET_ENVIRONMENT']='1'
        p=subprocess.Popen([str(image),'--db',str(db),'--port',str(u.port or 80)],stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True,env=env)
    return dict(state='backend_restart_started',pid=p.pid)


def request_repair(db,server,item):
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    with opener.open(server+'/',timeout=3) as r:page=r.read(2*1024*1024).decode()
    match=re.search(r"const csrf='([^']+)'",page)
    if not match:raise ValueError('Backend recovery token unavailable')
    req=urllib.request.Request(server+'/api/monitor/recover',data=json.dumps(dict(session_id=item['session'],kind=item['kind'])).encode(),headers={'Origin':server,'X-CSRF-Token':match.group(1),'Content-Type':'application/json'})
    with opener.open(req,timeout=5) as r:return json.load(r)


def check(db,server,*,notify=True,clock=None,probe=health,sender=post,repairer=request_repair,starter=restart_backend):
    db=Path(db).expanduser().resolve();server=valid_server(server)
    started=time.monotonic();clock=time.time() if clock is None else clock;folder=db.parent/'monitor';folder.mkdir(mode=0o700,parents=True,exist_ok=True)
    with (folder/'check.lock').open('a') as lease:
        try:fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return dict(state='already-checking')
        state=read(folder/'state.json',dict(sessions={},incidents={},outbox=[],history=[]))
        enabled=bool(read(folder/'config.json').get('auto_repair'))
        for item in state['outbox']:
            if item['state']=='sending':item['state']='uncertain'
        inspected=True
        try:
            findings,active,healthy=inspect(db,server,state,clock,probe) if db.is_file() else ({},set(),probe(server,db))
            state['read_failures']=0
        except (sqlite3.Error,ValueError,OSError):
            inspected=False
            state['read_failures']=state.get('read_failures',0)+1;active=set(state['sessions']);healthy=False;findings={}
            if state['read_failures']>=3:findings['records-unreadable']=dict(session=None,title='BrainDance',kind='records-unreadable',phase='monitor',message='연구 기록을 3회 연속 읽지 못했습니다. 원본 연구 기록은 변경하지 않았습니다.')
        try:target=slack_target(db)
        except (sqlite3.Error,OSError,ValueError):target={}
        recovery=[]
        if enabled and inspected and active:
            if not healthy and 'backend-down' in findings and clock-state.get('last_restart_attempt',0)>=300:
                state['last_restart_attempt']=clock
                try:recovery.append(starter(db,server))
                except (OSError,ValueError,sqlite3.Error):recovery.append(dict(state='backend_restart_failed'))
            if healthy:
                seen=set()
                for item in findings.values():
                    sid=item.get('session')
                    if not sid or sid in seen:continue
                    seen.add(sid)
                    try:recovery.append(dict(session=sid,**repairer(db,server,item)))
                    except (OSError,ValueError):recovery.append(dict(session=sid,state='recovery_request_failed'))
        def enqueue(key,item,recovered=False):
            text='*BrainDance 감시 · '+('진행 갱신 확인' if recovered else '자동 복구 확인' if enabled else '확인 필요')+'*\n'+html.escape(item['title'],quote=False)[:180]+'\n'+html.escape(item['message'],quote=False)[:500]+'\n단계: '+html.escape(item['phase'],quote=False)+ ('\n자동 수리 요청: '+', '.join(v['state'] for v in recovery)+' · 연구 종료 시각·사용량 기준 유지' if enabled else '\n감시자는 알림만 처리합니다. / 자동 모델 호출 0회')
            identity=key+':'+str(clock)+('recovered' if recovered else 'alert')
            state['outbox'].append(dict(id=identity,key=key,text=text,target=target_id(target),state='pending' if target else 'muted',retry_at=0,recovered=recovered))
            return identity
        for key,item in findings.items():
            incident=state['incidents'].get(key)
            if not incident or not incident.get('active'):
                event=enqueue(key,item);state['incidents'][key]=dict(active=True,item=item,event=event,opened_at=clock)
                state['history'].append(dict(at=clock,event='detected',**item))
        for key,incident in state['incidents'].items():
            if inspected and incident.get('active') and key not in findings:
                incident['active']=False;item=incident['item']
                sent=any(e['id']==incident['event'] and e['state']=='sent' for e in state['outbox'])
                if sent and (item.get('session') in active or key=='backend-down' and active and healthy):enqueue(key,{**item,'message':'이전 감시 조건이 해제됐습니다. 새 진행 기록 또는 백엔드 응답을 확인했습니다.'},True)
                state['history'].append(dict(at=clock,event='cleared' if item.get('session') in active else 'withdrawn',kind=item['kind'],session=item.get('session')))
        state['history']=state['history'][-100:];state['outbox']=state['outbox'][-200:]
        state['incidents']={k:v for k,v in state['incidents'].items() if v['active'] or v['opened_at']>clock-86400}
        state.update(last_check=stamp(),checked_epoch=clock,backend_healthy=healthy,active_sessions=len(active),findings=list(findings.values()),slack_ready=bool(target),mode='auto_recover' if enabled else 'alert_only',model_calls=0,recovery=recovery,elapsed_ms=round((time.monotonic()-started)*1000,2))
        save(folder/'state.json',state)
        if notify:
            for event in [e for e in state['outbox'] if e['state']=='pending' and e['retry_at']<=clock][:5]:
                if not inspected and event['key']!='records-unreadable':continue
                if not target or event['target']!=target_id(target) or not event['recovered'] and event['key'] not in findings:event['state']='cancelled';continue
                event['state']='sending';save(folder/'state.json',state)
                event['state'],delay=sender(target,event['text'],folder/'cacert.pem');event['retry_at']=clock+delay
                save(folder/'state.json',state)
        save(folder/'state.json',state)
        # Bounded local diagnostics; no research/model text or tokens are logged.
        log=folder/'service.log'
        if log.is_file() and log.stat().st_size>1024*1024:os.replace(log,folder/'service.previous.log')
        return {k:state[k] for k in ['last_check','backend_healthy','active_sessions','findings','slack_ready','mode','model_calls','elapsed_ms']}


def install(db,server):
    if sys.platform!='darwin':raise ValueError('자동 감시 설치는 macOS launchd를 사용합니다.')
    folder=db.parent/'monitor';folder.mkdir(mode=0o700,parents=True,exist_ok=True)
    source=Path(sys._MEIPASS)/'assets/brain_monitor.py' if getattr(sys,'frozen',False) else Path(__file__)
    script=folder/'brain_monitor.py';data=source.read_bytes()
    if script.is_file():shutil.copy2(script,folder/'brain_monitor.previous.py')
    fd,tmp=tempfile.mkstemp(dir=str(folder));os.fchmod(fd,0o600)
    with os.fdopen(fd,'wb') as stream:stream.write(data)
    os.replace(tmp,script)
    save(folder/'config.json',dict(auto_repair=True))
    import certifi
    shutil.copyfile(certifi.where(),folder/'cacert.pem');(folder/'cacert.pem').chmod(0o600)
    python=Path('/usr/bin/python3')
    if not python.is_file():raise ValueError('감시자 실행용 Python 3이 필요합니다.')
    plist=agent_path(db);plist.parent.mkdir(parents=True,exist_ok=True)
    if plist.is_file():
        old=plistlib.loads(plist.read_bytes())
        if old.get('Label')!=label(db) or str(script) not in old.get('ProgramArguments',[]):raise ValueError('같은 이름의 다른 서비스가 있어 설치를 중단했습니다.')
        shutil.copy2(plist,folder/'launchagent.previous.plist')
    settings=dict(Label=label(db),ProgramArguments=[str(python),'-I',str(script),'check','--db',str(db),'--server',server],StartInterval=INTERVAL,RunAtLoad=True,ProcessType='Background',Nice=10,LowPriorityIO=True,StandardOutPath=str(folder/'service.log'),StandardErrorPath=str(folder/'service.log'))
    plist.write_bytes(plistlib.dumps(settings));plist.chmod(0o600)
    domain='gui/'+str(os.getuid());subprocess.run(['launchctl','bootout',domain+'/'+label(db)],capture_output=True)
    result=subprocess.run(['launchctl','bootstrap',domain,str(plist)],capture_output=True)
    if result.returncode:raise ValueError('macOS 감시 서비스 등록을 완료하지 못했습니다.')
    return dict(installed=True,interval_seconds=INTERVAL,stall_minutes=STALL_SECONDS//60,service=label(db),mode='auto_recover',model_calls=0)
def status(db):
    installed=agent_path(db).is_file();loaded=False
    if installed and sys.platform=='darwin':loaded=subprocess.run(['launchctl','print','gui/'+str(os.getuid())+'/'+label(db)],capture_output=True).returncode==0
    state=read(db.parent/'monitor/state.json');enabled=read(db.parent/'monitor/config.json').get('auto_repair',False)
    return dict(installed=installed,service_loaded=loaded,last_check=state.get('last_check'),backend_healthy=state.get('backend_healthy'),active_sessions=state.get('active_sessions',0),findings=state.get('findings',[]),slack_ready=state.get('slack_ready',False),mode='auto_recover' if enabled else 'alert_only',model_calls=0,recovery=state.get('recovery',[]),elapsed_ms=state.get('elapsed_ms'))
def command(action,db,server,notify=True):
    db=Path(db).expanduser().resolve();server=valid_server(server)
    if action=='check':return check(db,server,notify=notify)
    if action=='status':return status(db)
    if action=='install':return install(db,server)
    if action in {'repair-on','repair-off'}:
        save(db.parent/'monitor/config.json',dict(auto_repair=action=='repair-on'));return status(db)
    if action=='uninstall':
        if sys.platform!='darwin':raise ValueError('macOS 감시 서비스가 아닙니다.')
        plist=agent_path(db)
        if plist.is_file():
            value=plistlib.loads(plist.read_bytes())
            if value.get('Label')!=label(db) or str(db.parent/'monitor/brain_monitor.py') not in value.get('ProgramArguments',[]):raise ValueError('다른 서비스의 등록 파일은 변경하지 않습니다.')
        subprocess.run(['launchctl','bootout','gui/'+str(os.getuid())+'/'+label(db)],capture_output=True);plist.unlink(missing_ok=True)
        return dict(installed=False,records_preserved=True)
    raise ValueError('감시 동작을 확인하세요.')
def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['status','check','install','uninstall','repair-on','repair-off'],nargs='?',default='status');p.add_argument('--db',type=Path,default=Path.home()/'Library/Application Support/BrainDance/tree.sqlite3');p.add_argument('--server',default='http://127.0.0.1:8766');p.add_argument('--json',action='store_true');p.add_argument('--no-notify',action='store_true');args=p.parse_args()
    try:
        result=command(args.action,args.db,args.server,not args.no_notify)
        if args.json or args.action!='check':print(json.dumps(result,ensure_ascii=False))
        return 0
    except (OSError,ValueError,sqlite3.Error):print('BrainDance 감시 확인 실패 · 로컬 서비스 로그와 설정을 확인하세요.',file=sys.stderr);return 1
if __name__=='__main__':raise SystemExit(main())
