"""Terminal client for the same loopback service, projects and model sessions as the app."""
import argparse
import asyncio
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid


LOGO_ASSETS=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent.parent))/'assets'
PHASES={'native-agent':'원본 관점 에이전트','native-tool':'원본 도구 실행','native-narration':'원본 연구 진행','quota-stop':'사용량 보호 중지','broad-exploration':'6개 관점의 넓은 탐색','novelty-search':'선행연구 재검색·검증','scout-search':'논문 탐색','native-pipeline':'자율 연구','native-discovery':'아이디어 탐색','native-implementation':'자율 구현·실험','native-review':'Reviewer 검토·개선','native-council':'Council 추가 평가','native-completed':'자율 연구 완료','preflight':'준비','environment':'환경 확인','exploration':'서버·코드 탐색','inspected':'탐색 완료',
 'literature':'논문 탐색','verification':'논문 확인','generation':'가설 생성','peer-review':'교차 평가',
 'chairman':'종합','coding':'실험 코드 작성','code-review':'코드 검토','registering':'계획 등록',
 'experiment_approval':'실행 코드 준비','blocked':'확인 필요','analysis':'결과 분석','analyzed':'분석 완료'}


def safe_text(value):
    text=str(value).replace('\r','\n')
    text=re.sub(r'\x1b(?:\][^\x07]*(?:\x07|\x1b\\)|\[[0-?]*[ -/]*[@-~]|.)','',text)
    return re.sub(r'[\x00-\x08\x0b-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]','',text)


def banner(width=80,color=False):
    result='  BrainDance'
    for size in ['wide','regular','small']:
        rows=(LOGO_ASSETS/('terminal-logo-'+size+'.txt')).read_text(encoding='utf-8').splitlines()
        if max(map(len,rows))+2<=width:
            result='\n'.join(['  '+row if row else '' for row in rows]+['','  BrainDance',''])
            break
    return '\x1b[38;2;123;181;148m'+result+'\x1b[0m' if color else result


def default_db():
    root=Path(os.environ.get('BRAINDANCE_DATA_DIR',Path.home()/'Library/Application Support/BrainDance'))
    return (root/'tree.sqlite3').expanduser().resolve()


def workspace_id(db):return hashlib.sha256(str(Path(db).expanduser().resolve()).encode()).hexdigest()


def install_launcher(directory=None):
    directory=Path(directory) if directory else Path.home()/'.local/bin'
    directory.mkdir(parents=True,exist_ok=True)
    target=directory/'braindance';marker='# BrainDance CLI launcher'
    if target.exists() or target.is_symlink():
        if target.is_symlink() or marker not in target.read_text():raise ClientError('기존 braindance 명령이 있습니다. '+str(target)+'를 먼저 확인하세요.')
    if getattr(sys,'frozen',False):
        from runtime_binary import pin
        command=[str(pin(sys.executable,default_db().parent/'runtime-binaries')),'--cli']
    else:command=[sys.executable,str(Path(__file__).resolve().parents[4]/'braindance.py')]
    body='#!/bin/sh\n'+marker+'\nexec '+shlex.join(command)+' "$@"\n'
    temporary=target.with_name('.braindance-'+uuid.uuid4().hex)
    try:
        temporary.write_text(body);temporary.chmod(0o755);os.replace(temporary,target)
    finally:temporary.unlink(missing_ok=True)
    if getattr(sys,'frozen',False):
        from host_repair import register_build
        register_build(default_db(),target)
    return str(target)


class ClientError(RuntimeError):pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def backend_environment():
    environment=os.environ.copy()
    if getattr(sys,'frozen',False):
        # The detached backend must own its one-file assets and bundled CA path;
        # the CLI bootloader removes the client's extraction directory on exit.
        environment['PYINSTALLER_RESET_ENVIRONMENT']='1'
        certificate=environment.get('SSL_CERT_FILE')
        if certificate and Path(certificate).is_relative_to(Path(sys._MEIPASS)):
            environment.pop('SSL_CERT_FILE')
    return environment


class Client:
    def __init__(self,url,db):
        parsed=urllib.parse.urlsplit(url)
        if parsed.scheme!='http' or parsed.hostname not in {'127.0.0.1','localhost'} or parsed.username or parsed.password or parsed.path not in {'','/'} or parsed.query or parsed.fragment:
            raise ClientError('같은 컴퓨터의 BrainDance 주소만 사용할 수 있습니다.')
        try:port=parsed.port if parsed.port is not None else 80
        except ValueError:raise ClientError('서버 포트를 확인하세요.')
        if not 1<=port<=65535:raise ClientError('서버 포트는 1–65535여야 합니다.')
        self.url='http://'+parsed.hostname+':'+str(port);self.db=Path(db).expanduser().resolve();self.csrf=None
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())

    def request(self,path,payload=None,_refreshed=False):
        headers={};body=None
        if payload is not None:
            if not self.csrf:
                html=self.request('/')
                match=re.search(r"const csrf='([^']+)'",html)
                if not match:raise ClientError('서버의 요청 보호 토큰을 확인할 수 없습니다.')
                self.csrf=match.group(1)
            headers={'Content-Type':'application/json','Origin':self.url,'X-CSRF-Token':self.csrf}
            body=json.dumps(payload,ensure_ascii=False).encode()
        request=urllib.request.Request(self.url+path,data=body,headers=headers)
        try:
            timeout=120 if path=='/api/project/purge' else 45 if path.split('?')[0] in {'/api/compute/probe','/api/providers','/api/providers/refresh','/api/notion/configure','/api/project/purge-preview','/api/project/delete'} else 8
            with self.opener.open(request,timeout=timeout) as response:
                data=response.read().decode('utf-8')
                return json.loads(data) if 'application/json' in response.headers.get('Content-Type','') else data
        except urllib.error.HTTPError as error:
            text=error.read().decode('utf-8',errors='replace')
            try:text=json.loads(text).get('error',text)
            except ValueError:pass
            if payload is not None and error.code==403 and text=='Same-origin request and CSRF token required' and not _refreshed:
                self.health();self.csrf=None
                return self.request(path,payload,_refreshed=True)
            raise ClientError(safe_text(text)[:2000]) from error

    def health(self):
        health=self.request('/api/health')
        if not isinstance(health,dict) or health.get('app')!='BrainDance':raise ClientError('해당 주소는 BrainDance 서버가 아닙니다.')
        if health.get('workspace_id')!=workspace_id(self.db):raise ClientError('실행 중인 서버의 작업공간이 다릅니다. --db와 --server를 확인하거나 앱을 최신 버전으로 다시 여세요.')
        return health

    def projects(self):
        return [p for p in self.request('/api/tree')['projects'] if not p.get('deleted_at')]

    def project(self,selector=None,*,deleted=False):
        projects=self.request('/api/project/trash')['projects'] if deleted else self.projects()
        if selector is None:
            if len(projects)==1:return projects[0]
            raise ClientError('프로젝트를 선택하세요. '+('/trash' if deleted else '/projects')+'로 목록을 확인하고 --project 이름 또는 ID를 사용하세요.')
        text=str(selector)
        exact=[p for p in projects if p['id']==text or p['title'].casefold()==text.casefold()]
        if len(exact)==1:return exact[0]
        if text.isdigit() and 1<=int(text)<=len(projects):return projects[int(text)-1]
        matches=[p for p in projects if p['id'].startswith(text)]
        if len(matches)!=1:raise ClientError('프로젝트를 하나로 특정할 수 없습니다. '+('/trash' if deleted else '/projects')+'로 확인하세요.')
        return matches[0]

    def root(self,project):
        return next(n for n in self.request('/api/tree')['nodes'] if n['project_id']==project['id'] and not n['parent_id'])

    def control(self,project):return self.request('/api/control?'+urllib.parse.urlencode(dict(project_id=project['id'])))
    def messages(self,project):return self.request('/api/chat?'+urllib.parse.urlencode(dict(project_id=project['id'])))['messages']

    def send(self,project,text,mode='auto',request_id=None,reply_to=None):
        payload=dict(node_id=self.root(project)['id'],content=text,mode=mode,request_id=request_id or str(uuid.uuid4()))
        if reply_to:payload['reply_to']=reply_to
        try:return self.request('/api/chat/send',payload)
        except (urllib.error.URLError,TimeoutError) as error:
            raise ClientError('전송 결과를 확인하지 못했습니다. /history로 확인하세요. 같은 요청을 재확인할 ID: '+payload['request_id']) from error


def connect(args):
    db=Path(getattr(args,'db',default_db())).expanduser().resolve()
    port=getattr(args,'port',8766);url=getattr(args,'server',None) or 'http://127.0.0.1:'+str(port)
    client=Client(url,db)
    try:client.health();return client
    except (urllib.error.URLError,ConnectionError,TimeoutError):
        if getattr(args,'no_start',False) or getattr(args,'server',None):raise ClientError('BrainDance 서버에 연결할 수 없습니다.')
    db.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    import fcntl
    with (db.parent/'.cli-launch.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        try:client.health();return client
        except (urllib.error.URLError,ConnectionError,TimeoutError):pass
        if getattr(sys,'frozen',False):
            from runtime_binary import pin
            command=[str(pin(sys.executable,db.parent/'runtime-binaries')),'--db',str(db),'--port',str(port)]
        else:command=[sys.executable,str(Path(__file__).resolve().parents[4]/'braindance.py'),'serve','--db',str(db),'--port',str(port)]
        log_path=db.parent/'cli-backend.log'
        fd=os.open(log_path,os.O_CREAT|os.O_APPEND|os.O_WRONLY,0o600)
        with os.fdopen(fd,'ab') as log:process=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True,close_fds=True,env=backend_environment())
        deadline=time.monotonic()+25
        while time.monotonic()<deadline:
            if process.poll() is not None:raise ClientError('연구 서버를 시작하지 못했습니다. '+str(log_path)+'를 확인하세요.')
            try:client.health();return client
            except (urllib.error.URLError,ConnectionError,TimeoutError):time.sleep(.2)
        raise ClientError('서버 시작을 기다리고 있습니다. 잠시 후 같은 명령으로 다시 연결하세요.')


def display_message(message,full=False):
    role=message['role'];label={'user':'나','assistant':'Codex','report':'연구 보고','status':'진행'}[role]
    if role=='status':text=PHASES.get(message.get('phase'),message.get('phase',''))+' · '+message['content']
    else:text=(message.get('title','')+'\n' if message.get('title') else '')+message['content']
    if not full and role in {'report','status'} and len(text)>900:text=text[:900]+'\n… /history --full 로 전체 기록을 볼 수 있습니다.'
    if role=='assistant' and message['state'] in {'queued','preparing','running'}:text='답변 작성 중…'
    ref=message.get('metadata',{}).get('reply_to')
    return '\n'+label+(' · 답글: '+ref['title'] if ref else '')+'\n'+safe_text(text)+'\n'


def status_text(project,state):
    usage=state.get('usage');session=state.get('session');lines=[project['title']]
    if session:lines.append({'running':'자동모드 ON','paused':'일시정지','blocked':'확인 필요','completed':'완료','stopped':'중지'}.get(session['status'],session['status'])+' · '+session['message'])
    if session and session.get('config',{}).get('research_style')=='scout':lines.append('연구 방식 · 논문 탐색 / 작은 실험')
    if usage and usage.get('policy')=='until_deadline':
        from terminal_presenter import deadline_text
        lines.append(deadline_text(usage['deadline_epoch']));lines.append('모델 호출 '+str(usage['calls'])+'회 · 보고된 토큰 '+str(usage['observed_tokens'])+' · 횟수·토큰 제한 없음')
    elif usage:lines.append('모델 호출 '+str(usage['calls'])+' / '+str(usage['max_calls'])+' · 남은 '+str(max(0,usage['max_calls']-usage['calls']))+'회 · 토큰 예상·예약 '+str(usage['charged_tokens'])+' / '+str(usage['token_budget']))
    for job in state.get('jobs',[]):
        lines.append('연구 '+job['state']+' · '+PHASES.get(job['phase'],job['phase'])+' · job:'+job['id'])
    if session and session['status']=='blocked':lines.append('답글 대상: session:'+session['id'])
    for run in state['runs']:lines.append('실험 '+run['state']+' · '+run['title']+' · '+run['id'])
    anth=(usage or {}).get('anthropic_usage',{})
    if any(anth.values()):lines.append('메인 Claude 확인분 · 새 입력 '+format(anth.get('input_tokens',0),',')+' · 출력 '+format(anth.get('output_tokens',0),',')+' · 캐시 읽기 '+format(anth.get('cache_read_input_tokens',0),',')+' · 캐시 쓰기 '+format(anth.get('cache_creation_input_tokens',0),','))
    return safe_text('\n'.join(lines))


def file_size(value):
    size=float(value)
    for unit in ['B','KiB','MiB','GiB','TiB']:
        if size<1024 or unit=='TiB':return f'{size:,.1f} {unit}'
        size/=1024


def purge_summary(preview):
    counts=preview.get('counts',{})
    return safe_text('\n'.join([preview['title'],'완전 삭제하면 복원할 수 없습니다.',
        '노드 '+str(counts.get('nodes',0))+'개 · 기록 '+str(counts.get('notes',0))+'개 · 대화 '+str(counts.get('messages',0))+'개',
        '실험 '+str(counts.get('experiments',0))+'개 · 실행 '+str(counts.get('runs',0))+'개',
        '정리 대상 로컬 파일: '+file_size(preview.get('local_file_bytes',0)),
        '프로젝트의 관리 파일·로컬 기록을 삭제하고 데이터베이스 공간을 정리합니다.',
        'SSH 서버 파일과 외부 데이터·코드는 삭제하지 않습니다.']))


def project_action(client,args,current=None):
    command=args.command
    if command=='trash':return client.request('/api/project/trash')['projects']
    selector=getattr(args,'project',None)
    project=client.project(selector,deleted=command in {'restore','purge'}) if selector is not None or command!='delete' or current is None else current
    if command=='purge':
        preview=client.request('/api/project/purge-preview?'+urllib.parse.urlencode(dict(project_id=project['id'])))
        if args.preview:return dict(action='preview',**preview)
        name=args.confirm_name
        if name is None:
            if not sys.stdin.isatty() or getattr(args,'json',False):raise ClientError(purge_summary(preview)+'\n먼저 --preview로 확인한 뒤 --confirm-name에 프로젝트 이름을 정확히 입력하세요.')
            print(purge_summary(preview))
            name=input('완전 삭제할 프로젝트 이름을 그대로 입력하세요 (Enter 취소): ')
        if name!=preview['title']:raise ClientError('프로젝트 이름이 일치하지 않아 완전 삭제하지 않았습니다.')
        result=client.request('/api/project/purge',dict(project_id=project['id'],confirmation_name=name))
    else:
        if project.get('cleanup_pending'):raise ClientError('이미 완전 삭제된 프로젝트의 파일 정리가 남아 있습니다. 복원할 수 없으며 완전 삭제를 다시 시도하세요.')
        result=client.request('/api/project/'+command,dict(project_id=project['id']))
    return {**result,'project_id':project['id'],'title':project['title'],'action':command}


def parser():
    common=argparse.ArgumentParser(add_help=False)
    for name,kw in [('db',dict(type=Path)),('server',{}),('port',dict(type=int)),('project',{})]:common.add_argument('--'+name,default=argparse.SUPPRESS,**kw)
    for name in ['json','no-start','no-banner','no-color','plain']:common.add_argument('--'+name,action='store_true',default=argparse.SUPPRESS)
    p=argparse.ArgumentParser(prog='braindance',description='BrainDance 프로젝트 대화·연구 터미널',parents=[common])
    sub=p.add_subparsers(dest='command')
    sub.add_parser('install-cli',parents=[common])
    q=sub.add_parser('monitor',parents=[common]);q.add_argument('action',choices=['status','install','check','uninstall','repair-on','repair-off','repair-source'],nargs='?',default='status');q.add_argument('--no-notify',action='store_true');q.add_argument('--source',type=Path);q.add_argument('--python',type=Path)
    for name in ['delete','trash','restore','purge']:
        q=sub.add_parser(name,parents=[common])
        if name=='purge':
            q.add_argument('--preview',action='store_true',help='Show local records and files to remove without deleting')
            q.add_argument('--confirm-name',help='Exact project name required for permanent deletion without an interactive prompt')
    for name in ['projects','status','tree','connections','devices','tasks']:
        q=sub.add_parser(name,parents=[common]);
        if name=='devices':q.add_argument('profile')
    q=sub.add_parser('history',parents=[common]);q.add_argument('--full',action='store_true');q.add_argument('--last',type=int,default=10)
    q=sub.add_parser('chat',parents=[common]);q.add_argument('message');q.add_argument('--mode',choices=['auto','ask','next','restart'],default='auto');q.add_argument('--no-wait',action='store_true');q.add_argument('--timeout',type=int,default=300);q.add_argument('--request-id');q.add_argument('--reply-to',help='job:ID, session:ID 또는 run:ID')
    q=sub.add_parser('limits',parents=[common]);q.add_argument('--calls',type=int);q.add_argument('--tokens',type=int)
    q.add_argument('--hours',type=float);q.add_argument('--experiment-minutes',type=float,help='Optional maximum minutes per experiment; 0 selects automatic allocation')
    q=sub.add_parser('auto',parents=[common]);q.add_argument('action',choices=['start','pause','resume','stop','economy','standard']);q.add_argument('--cycles',type=int,default=3);q.add_argument('--calls',type=int,default=40);q.add_argument('--tokens',type=int,default=1500000);q.add_argument('--context',default='');q.add_argument('--mode',choices=['lite','balanced','deep'],default='balanced');q.add_argument('--reuse-research',action='store_true',help='Reuse this project\'s completed Council and verified literature; re-author and review the next experiment')
    q.add_argument('--research-scope',choices=['full','ideation'],help='Original full research or original idea-discovery only, including diagnostic pilots')
    q.add_argument('--wait-for-quota',action='store_true',help='On resume, wait without model calls until the allowance baseline is available')
    q.add_argument('--hours',type=float);q.add_argument('--experiment-minutes',type=float,help='Optional maximum minutes per experiment; 0 selects automatic allocation');q.add_argument('--standard',action='store_true',help='Use standard discovery/review models instead of the economy default');q.add_argument('--bounded',action='store_true',help='Legacy count-budget mode instead of deadline-only autonomous research')
    q=sub.add_parser('interests',parents=[common]);q.add_argument('--interest',action='append');q.add_argument('--bridge',action='append');q.add_argument('--clear-bridges',action='store_true');q.add_argument('--style',choices=['focused','scout']);q.add_argument('--days',type=int);q.add_argument('--papers',type=int);q.add_argument('--pilots',type=int);q.add_argument('--seconds',type=int);q.add_argument('--gain',type=float);q.add_argument('--seeds',type=int)
    q.add_argument('--runtime-policy',choices=['auto','fixed'],help='Auto allocates remaining project time; fixed enforces --seconds as a hard cap')
    q=sub.add_parser('scout',parents=[common]);q.add_argument('action',choices=['start','status','pause','resume','stop'],default='status',nargs='?');q.add_argument('--calls',type=int,default=80);q.add_argument('--tokens',type=int,default=3000000);q.add_argument('--context',default='');q.add_argument('--mode',choices=['lite','balanced','deep'],default='lite')
    q.add_argument('--hours',type=float);q.add_argument('--experiment-minutes',type=float,help='Optional maximum minutes per experiment; 0 selects automatic allocation');q.add_argument('--standard',action='store_true',help='Use standard discovery/review models instead of the economy default');q.add_argument('--bounded',action='store_true')
    q=sub.add_parser('new',parents=[common]);q.add_argument('name');q.add_argument('--goal',required=True);q.add_argument('--target',default='local');q.add_argument('--devices',default='cpu');q.add_argument('--minutes',type=int,default=30);q.add_argument('--interest',action='append',default=[]);q.add_argument('--bridge',action='append',default=[]);q.add_argument('--style',choices=['focused','scout'],default='focused')
    q.add_argument('--start',action='store_true',help='Create and immediately start automatic research within the selected limits');q.add_argument('--calls',type=int);q.add_argument('--tokens',type=int);q.add_argument('--cycles',type=int);q.add_argument('--context',default='');q.add_argument('--mode',choices=['lite','balanced','deep'])
    q.add_argument('--hours',type=float);q.add_argument('--experiment-minutes',type=float,help='Optional maximum minutes per experiment; 0 selects automatic allocation');q.add_argument('--standard',action='store_true',help='Use standard discovery/review models instead of the economy default');q.add_argument('--bounded',action='store_true')
    q=sub.add_parser('target',parents=[common]);q.add_argument('profile');q.add_argument('--devices',required=True);q.add_argument('--minutes',type=int,default=30)
    q=sub.add_parser('connection',parents=[common]);q.add_argument('alias');q.add_argument('--name')
    q=sub.add_parser('logs',parents=[common]);q.add_argument('kind',choices=['job','run']);q.add_argument('id')
    q=sub.add_parser('report',parents=[common]);q.add_argument('action',choices=['status','build','open'],default='status',nargs='?')
    q=sub.add_parser('slack',parents=[common]);q.add_argument('action',choices=['status','setup','send','test','disconnect','remote-status','remote-setup','remote-off','remote-forget'],default='status',nargs='?');q.add_argument('--member');q.add_argument('--token-stdin',action='store_true');q.add_argument('--request-id');q.add_argument('--app-token-stdin',action='store_true')
    q=sub.add_parser('task',parents=[common]);q.add_argument('action',choices=['stop','resume']);q.add_argument('id')
    q=sub.add_parser('notion',parents=[common]);q.add_argument('action',choices=['status','setup','sync','disconnect'],default='status',nargs='?');q.add_argument('--parent');q.add_argument('--auto',action=argparse.BooleanOptionalAction,default=None)
    for name in ['new','auto','scout']:
        group=sub.choices[name].add_mutually_exclusive_group()
        group.add_argument('--quota-drop-percent',type=int,help='Stop after remaining allowance falls this many percentage points from launch/continuation')
        group.add_argument('--no-quota-guard',action='store_true',help='Explicitly disable the account allowance stop policy')
    return p


def profile_for(client,selector):
    profiles=client.request('/api/compute')['profiles'];matches=[p for p in profiles if selector in {p['id'],p['name'],p.get('host')}]
    if len(matches)!=1:raise ClientError('연결을 하나로 특정할 수 없습니다. connections로 확인하세요.')
    return matches[0]


def time_options(args):
    result=dict(execution_policy='bounded' if args.bounded else 'until_deadline',orchestration='single' if args.bounded else 'hypothesis-tasks',cost_profile='standard' if args.standard else 'economy')
    if args.hours is not None:result['duration_seconds']=int(args.hours*3600)
    if getattr(args,'quota_drop_percent',None) is not None:result['quota_drop_percent']=args.quota_drop_percent
    if getattr(args,'no_quota_guard',False):result['quota_drop_percent']=None
    if args.experiment_minutes is not None:result['experiment_timeout_seconds']=int(args.experiment_minutes*60) if args.experiment_minutes else None
    return result


def continuation_options(client,project,args):
    if args.hours is None:raise ClientError('중지한 연구를 이어가려면 --hours로 새 시간을 지정하세요.')
    state=client.request('/api/control?'+urllib.parse.urlencode(dict(project_id=project['id'])))
    if not state.get('session'):raise ClientError('이어갈 연구가 없습니다.')
    result=dict(session_id=state['session']['id'],duration_seconds=int(args.hours*3600))
    if args.quota_drop_percent is not None:result['quota_drop_percent']=args.quota_drop_percent
    if args.no_quota_guard:result['quota_drop_percent']=None
    return result


def dispatch(client,args,project=None):
    command=args.command
    if command in {'delete','trash','restore','purge'}:return project_action(client,args,project)
    if command=='projects':return client.projects()
    if command=='connections':return client.request('/api/compute')['profiles']
    if command=='connection':return client.request('/api/compute/profile',dict(name=args.name or args.alias,kind='ssh',host=args.alias,user='',port=None,identity_file=''))
    if command=='devices':return client.request('/api/compute/probe',dict(profile_id=profile_for(client,args.profile)['id']))
    if command=='slack':
        if args.action=='remote-status':return client.request('/api/slack/remote')
        if args.action=='remote-off':return client.request('/api/slack/remote/configure',dict(enabled=False))
        if args.action=='remote-forget':return client.request('/api/slack/remote/disconnect',{})
        if args.action=='remote-setup':
            import getpass
            if not sys.stdin.isatty() and not args.app_token_stdin:raise ClientError('/slack remote 숨김 입력 또는 --app-token-stdin을 사용하세요.')
            token=sys.stdin.read().strip() if args.app_token_stdin else getpass.getpass('Slack App-Level Token(xapp-, 숨김): ').strip()
            return client.request('/api/slack/remote/configure',dict(app_token=token,enabled=True))
        if args.action=='status':return client.request('/api/slack')
        if args.action=='disconnect':return client.request('/api/slack/disconnect',{})
        if args.action in {'send','test'}:
            payload=dict(request_id=args.request_id or str(uuid.uuid4()),test=args.action=='test')
            if args.action=='send':payload['project_id']=client.project(args.project or (project or {}).get('id'))['id']
            return client.request('/api/slack/send',payload)
        import getpass
        if not sys.stdin.isatty() and not args.token_stdin:raise ClientError('/slack 숨김 입력 또는 --token-stdin으로 봇 토큰을 등록하세요.')
        if args.token_stdin and not args.member:raise ClientError('--token-stdin을 사용할 때는 --member에 본인 멤버 ID를 입력하세요.')
        member=args.member or input('본인 Slack 멤버 ID: ').strip()
        token=sys.stdin.read().strip() if args.token_stdin else getpass.getpass('Slack 봇 토큰(xoxb-, 숨김): ').strip()
        return client.request('/api/slack/configure',dict(member_id=member,token=token,enabled=True))
    if command=='new':
        record=client.request('/api/project',dict(name=args.name,goal=args.goal,research_preferences=dict(style=args.style,interests=args.interest,bridge_fields=args.bridge),compute=dict(profile_id=profile_for(client,args.target)['id'],device_ids=args.devices.split(','),max_parallel_runs=1,time_budget_minutes=args.minutes,auto_run=False)))
        if args.start:
            scouting=args.style=='scout'
            try:record['automatic']=client.request('/api/control/automatic',dict(project_id=record['project_id'],action='start',**time_options(args),research_style=args.style,max_cycles=args.cycles if args.cycles is not None else (2 if scouting else 3),max_model_calls=args.calls if args.calls is not None else (80 if scouting else 40),token_budget=args.tokens if args.tokens is not None else (3000000 if scouting else 1500000),context_path=args.context,mode=args.mode or ('lite' if scouting else 'balanced')))
            except ClientError as error:raise ClientError('프로젝트는 생성됐지만 자동 시작에 실패했습니다. 프로젝트 ID: '+record['project_id']+' · '+str(error)) from error
        return record
    if command=='notion' and args.action!='sync':
        if args.action=='disconnect':return client.request('/api/notion/disconnect',{})
        state=client.request('/api/notion')
        if args.action=='status':return state
        import getpass
        parent=args.parent or (state.get('link') or {}).get('parent_id')
        if not parent:raise ClientError('--parent에 결과를 저장할 Notion 페이지 URL을 입력하세요.')
        if not sys.stdin.isatty():raise ClientError('Notion 토큰은 /notion의 숨김 입력으로 등록하세요.')
        token=getpass.getpass('Notion 토큰 (입력 숨김, 기존 연결 유지 시 Enter): ')
        return client.request('/api/notion/configure',dict(parent=parent,token=token,auto_sync=args.auto if args.auto is not None else True))
    project=client.project(args.project) if hasattr(args,'project') else project or client.project()
    if command=='interests':
        mapping={'interest':'interests','bridge':'bridge_fields','style':'style','days':'lookback_days','papers':'max_papers','pilots':'max_pilots','seconds':'pilot_seconds','runtime_policy':'runtime_policy','gain':'min_improvement','seeds':'min_seeds'}
        changes={field:getattr(args,key) for key,field in mapping.items() if getattr(args,key,None) is not None}
        if args.clear_bridges:changes['bridge_fields']=[]
        if changes:return client.request('/api/project/research-settings',dict(project_id=project['id'],settings=changes))
        return client.request('/api/project/research-settings?'+urllib.parse.urlencode(dict(project_id=project['id'])))
    if command=='scout':
        if args.action=='status':return client.control(project)
        payload=dict(project_id=project['id'],action=args.action)
        if args.action=='start':payload.update(**time_options(args),research_style='scout',max_model_calls=args.calls,token_budget=args.tokens,context_path=args.context,mode=args.mode)
        elif args.action=='resume' and (args.hours is not None or args.quota_drop_percent is not None or args.no_quota_guard):payload.update(continuation_options(client,project,args))
        return client.request('/api/control/automatic',payload)
    if command in {'report','notion'}:
        query='?'+urllib.parse.urlencode(dict(project_id=project['id']))
        if command=='report' and args.action=='build':return client.request('/api/reports/build',dict(project_id=project['id']))
        if command=='notion' and args.action=='sync':return client.request('/api/notion/sync',dict(project_id=project['id']))
        state=client.request('/api/reports'+query)
        if command=='report' and args.action=='open':
            if not state.get('report'):raise ClientError('먼저 report build로 보고서를 만들어 주세요.')
            import webbrowser
            webbrowser.open(client.url+'/api/reports/preview'+query)
        return state
    if command=='tasks':return client.control(project).get('tasks',[])
    if command=='task':return client.request('/api/control/task',dict(project_id=project['id'],task_id=args.id,action=args.action))
    if command=='status':
        state=client.control(project)
        jobs=client.request('/api/research?'+urllib.parse.urlencode(dict(project_id=project['id'])))['jobs']
        state['jobs']=[{k:j[k] for k in ['id','state','phase','message']} for j in jobs[:1]]
        return state
    if command=='history':return client.messages(project)[-max(1,min(120,args.last)):]
    if command=='tree':return [n for n in client.request('/api/tree')['nodes'] if n['project_id']==project['id']]
    if command=='target':
        return client.request('/api/compute/assignment',dict(project_id=project['id'],profile_id=profile_for(client,args.profile)['id'],device_ids=args.devices.split(','),max_parallel_runs=1,time_budget_minutes=args.minutes,auto_run=False))
    if command=='logs':
        if args.kind=='run':value=client.request('/api/run?'+urllib.parse.urlencode(dict(id=args.id)))
        else:value=client.request('/api/research/job?'+urllib.parse.urlencode(dict(id=args.id)))
        if value['project_id']!=project['id']:raise ClientError('다른 프로젝트의 실행 기록입니다.')
        return value
    if command=='limits':
        state=client.control(project)
        if args.hours is not None or args.experiment_minutes is not None:
            payload=dict(project_id=project['id'],action='deadline')
            if args.hours is not None:payload['duration_seconds']=int(args.hours*3600)
            else:payload.update(deadline_epoch=state['session']['config']['deadline_epoch'],duration_seconds=state['session']['config']['duration_seconds'])
            if args.experiment_minutes is not None:payload['experiment_timeout_seconds']=int(args.experiment_minutes*60) if args.experiment_minutes else None
            return client.request('/api/control/automatic',payload)
        if args.calls is None and args.tokens is None:return state.get('usage')
        if not state.get('session') or not state.get('usage'):raise ClientError('자동모드 실행 한도를 먼저 설정하세요.')
        return client.request('/api/control/automatic',dict(project_id=project['id'],action='limits',session_id=state['session']['id'],max_model_calls=args.calls if args.calls is not None else state['usage']['max_calls'],token_budget=args.tokens if args.tokens is not None else state['usage']['token_budget']))
    if command=='auto':
        if args.action in {'economy','standard'}:return client.request('/api/control/automatic',dict(project_id=project['id'],action='cost_profile',cost_profile=args.action))
        payload=dict(project_id=project['id'],action=args.action)
        if args.research_scope is not None:
            if args.action not in {'start','resume'}:raise ClientError('연구 범위는 시작 또는 새 시간으로 이어갈 때 설정하세요.')
            payload['research_scope']=args.research_scope
        if args.wait_for_quota:
            if args.action!='resume':raise ClientError('사용량 대기는 이어가기에서 설정하세요.')
            payload['wait_for_quota']=True
        if args.action=='start':
            payload.update(**time_options(args),max_cycles=args.cycles,max_model_calls=args.calls,token_budget=args.tokens,context_path=args.context,mode=args.mode)
            if args.reuse_research:payload['reuse_research']=True
        elif args.action=='resume' and (args.hours is not None or args.quota_drop_percent is not None or args.no_quota_guard or args.research_scope is not None or args.wait_for_quota):payload.update(continuation_options(client,project,args))
        return client.request('/api/control/automatic',payload)
    if command=='chat':
        text=sys.stdin.read() if args.message=='-' else args.message;reference=None
        if args.reply_to:
            kind,sep,identity=args.reply_to.partition(':')
            if not sep or kind not in {'job','run','session'} or not identity:raise ClientError('답글 대상은 job:ID, run:ID 또는 session:ID여야 합니다.')
            reference=dict(type=kind,id=identity)
        reply=client.send(project,text,args.mode,args.request_id,reference)
        if args.no_wait:return reply
        deadline=time.monotonic()+args.timeout
        while reply['state'] in {'queued','preparing','running'}:
            if time.monotonic()>deadline:raise ClientError('답변 대기를 종료했습니다. 작업은 계속됩니다. history로 확인하세요. 요청 ID: '+reply['request_id'])
            time.sleep(.5)
            reply=next((m for m in client.messages(project) if m['id']==reply['id']),reply)
        return reply
    raise ClientError('지원하지 않는 명령입니다.')


def output(value,args,project=None):
    if args.command=='tasks' and not getattr(args,'json',False):
        for task in value:print(task['id']+' · '+task['state']+' · '+task['title'])
        if not value:print('가설별 작업이 아직 없습니다.')
        return
    if getattr(args,'json',False):print(json.dumps(value,ensure_ascii=False,allow_nan=False));return
    if args.command=='slack':
        if args.action.startswith('remote-'):
            print('Slack DM 지시 · '+safe_text(value.get('connection','disabled'))+' · 선택 프로젝트 '+safe_text(value.get('project_title') or '없음'))
            if value.get('error'):print(safe_text(value['error']))
            return
        if 'state' in value:print('개인 DM 전송 '+value['state'])
        else:print('Slack 개인 DM '+('연결됨 · '+str(value.get('workspace') or '') if value.get('connected') else '연결 전'));print('전체 프로젝트 자동 결과 알림 '+('ON' if value.get('enabled') else 'OFF'))
        return
    if args.command in {'report','notion'}:
        if 'id' in value and 'state' in value:print('처리 대기 · 결과 탭 또는 report status로 확인하세요.')
        elif value=={'connected':False}:print('Notion 연결을 해제했습니다.')
        else:
            from terminal_presenter import report_view
            print(safe_text(report_view(value)))
    elif args.command in {'projects','trash'}:
        for i,p in enumerate(value,1):print(str(i)+'. '+safe_text(p['title'])+'  '+p['id']+(' · 정리 미완료' if p.get('cleanup_pending') else ''))
        if not value:print('휴지통이 비어 있습니다.' if args.command=='trash' else '프로젝트가 없습니다. new 명령으로 추가하세요.')
    elif args.command in {'delete','restore','purge'}:
        if value['action']=='preview':print(purge_summary(value))
        elif value['action']=='purge':
            print(('정리 미완료: ' if value.get('cleanup_pending') else '완전 삭제: ')+safe_text(value['title']))
            print('로컬 파일 '+file_size(value.get('removed_file_bytes',0))+' · 데이터베이스 '+file_size(value.get('reclaimed_database_bytes',0))+' 정리')
            if value.get('error'):print(safe_text(value['error'])+'\n휴지통에서 같은 프로젝트의 완전 삭제를 다시 시도하세요.')
        else:print(('휴지통으로 이동: ' if args.command=='delete' else '복원: ')+safe_text(value['title']))
    elif args.command=='interests':
        print('연구 방식: '+('탐색' if value['style']=='scout' else '집중 연구'))
        print('관심 분야: '+(', '.join(value['interests']) or '미설정'))
        print('연결 분야: '+(', '.join(value['bridge_fields']) or '자동 선택'))
        print(f"최근 {value['lookback_days']}일 · 논문 {value['max_papers']}개 · 작은 실험 {value['max_pilots']}회 × 최대 {value['pilot_seconds']}초 · 상대 개선 {value['min_improvement']:.1%} · seed {value['min_seeds']}개")
    elif args.command=='status':print(status_text(project,value))
    elif args.command=='chat':print(display_message(value,True))
    elif args.command=='history':
        for message in value:print(display_message(message,args.full))
    elif args.command=='tree':
        for n in value:print('  '*n['depth']+('- ' if n['status']!='discarded' else 'x ')+safe_text(n['title'])+'  ['+n['status']+']')
    elif args.command in {'auto','limits','scout'}:
        usage=value.get('usage',value) if value else None
        if args.command in {'auto','scout'}:print(status_text(project,value))
        elif usage:
            if usage.get('policy')=='until_deadline':
                from terminal_presenter import deadline_text
                print(deadline_text(usage['deadline_epoch'])+' · 호출 '+str(usage['calls'])+'회 · 보고된 토큰 '+str(usage['observed_tokens'])+' · 횟수·토큰 제한 없음')
            else:print('모델 호출 '+str(usage['calls'])+' / '+str(usage['max_calls'])+' · 토큰 예상·예약 '+str(usage['charged_tokens'])+' / '+str(usage['token_budget']))
        else:print('자동모드 실행 한도가 아직 없습니다.')
    elif args.command=='connections':
        for profile in value:print(safe_text(profile['name'])+' · '+profile['kind']+' · '+profile['id'])
    elif args.command=='devices':
        print('연결됨' if value.get('connected') else '연결 실패')
        if value.get('error'):print(safe_text(value['error']))
        for device in value.get('devices',[]):
            prefix='GPU '+str(device['index'])+' · ' if type(device.get('index')) is int else ''
            print(prefix+safe_text(device.get('name',device['id']))+' · '+safe_text(device['id']))
    elif args.command=='new':print('프로젝트 생성'+(' · 자동 연구 시작' if value.get('automatic') else '')+': '+safe_text(value['node']['metadata']['project_name'])+' · '+value['project_id'])
    elif args.command=='connection':print('연결 등록: '+safe_text(value['name'])+' · '+value['id'])
    elif args.command=='target':print('실행 환경 저장: '+safe_text(value['profile_id'])+' · '+safe_text(', '.join(value['device_ids'])))
    elif args.command=='logs':
        print(safe_text(value.get('state',''))+' · '+safe_text(value.get('message',value.get('error') or '')))
        for key in ['progress','events','stdout_tail','stderr_tail','files']:
            if value.get(key):print(safe_text(json.dumps(value[key],ensure_ascii=False,indent=2) if not isinstance(value[key],str) else value[key]))
    else:print(safe_text(json.dumps(value,ensure_ascii=False,indent=2)))


HELP='''/projects · /use 번호 또는 이름 · /new 이름 --goal "연구 목표"
/delete [--project 이름] · /trash · /restore --project 이름 또는 ID
/purge --project 이름 또는 ID [--preview] · 완전 삭제는 이름 확인 필요
/status · /history [--full] · /tree · /connections · /devices 연결
/auto start --context "연구 폴더" · /auto pause|resume|stop
/limits --calls 총횟수 · /limits --tokens 총토큰
/ask 질문 · /next 다음 단계 지시 · /restart 중지 후 재준비 지시
/reply job:ID 메시지 · /logs job|run ID · /exit (종료)
/report status|build|open · /notion status|setup|sync|disconnect
/slack status|setup|test|disconnect · 전체 프로젝트 개인 DM 알림
그냥 입력하면 같은 프로젝트 대화로 전송됩니다. Enter 전송 · Alt+Enter 줄바꿈.'''


class Console:
    def __init__(self,client,args):
        self.client=client;self.args=args;self.project=None;self.seen={};self.sent=set();self.toolbar='프로젝트 선택';self.error=None

    def select(self,selector):
        self.project=self.client.project(selector);messages=self.client.messages(self.project)
        self.seen={m['id']:self.signature(m) for m in messages}
        self.toolbar=self.project['title']
        print('\n'+safe_text(self.project['title']))
        if messages:print('최근 기록 '+str(len(messages))+'개 · /history 로 확인')

    @staticmethod
    def signature(m):return json.dumps([m['state'],m['content'],m.get('phase')],ensure_ascii=False)

    async def monitor(self):
        while True:
            try:
                if self.project:
                    project=self.project;messages=await asyncio.to_thread(self.client.messages,project)
                    if not self.project or project['id']!=self.project['id']:continue
                    for message in messages:
                        signature=self.signature(message)
                        if self.seen.get(message['id'])==signature:continue
                        self.seen[message['id']]=signature
                        if message['role']=='user' and message.get('request_id') in self.sent:continue
                        print(display_message(message),flush=True)
                    state=await asyncio.to_thread(self.client.control,project)
                    if not self.project or project['id']!=self.project['id']:continue
                    usage=state.get('usage');session=state.get('session')
                    from terminal_presenter import deadline_text
                    self.toolbar=project['title']+' · '+(session['status'] if session else '수동')+(' · 호출 '+str(usage['calls'])+('회 · '+deadline_text(usage['deadline_epoch']) if usage.get('policy')=='until_deadline' else '/'+str(usage['max_calls'])) if usage else '')
                    if getattr(self,'prompt_session',None):self.prompt_session.app.invalidate()
                    self.error=None
            except (ClientError,urllib.error.URLError,TimeoutError,OSError) as error:
                text=safe_text(error)
                if text!=self.error:print('\n연결 확인: '+text);self.error=text
            await asyncio.sleep(2)

    async def handle(self,line):
        if not line.strip():return True
        if not line.startswith('/'):
            if not self.project:raise ClientError('/use로 프로젝트를 선택하세요.')
            request_id=str(uuid.uuid4());self.sent.add(request_id)
            await asyncio.to_thread(self.client.send,self.project,line,'auto',request_id)
            return True
        words=shlex.split(line[1:]);command=words[0] if words else 'help'
        if command in {'quit','exit'}:return False
        if command=='help':print(HELP);return True
        if command=='use':
            if len(words)<2:raise ClientError('/use 프로젝트 번호 또는 이름')
            await asyncio.to_thread(self.select,' '.join(words[1:]));return True
        if command in {'ask','next','restart','reply'}:
            if not self.project:raise ClientError('/use로 프로젝트를 선택하세요.')
            mode={'ask':'ask','next':'next','restart':'restart','reply':'auto'}[command]
            text=line[1+len(command):].strip();reference=None
            if command=='reply':
                ref,_,text=text.partition(' ');kind,sep,identity=ref.partition(':')
                if not sep or kind not in {'job','session','run'}:raise ClientError('/reply job:ID 메시지')
                reference=dict(type=kind,id=identity)
            request_id=str(uuid.uuid4());self.sent.add(request_id)
            await asyncio.to_thread(self.client.send,self.project,text,mode,request_id,reference);return True
        try:args=parser().parse_args(words)
        except SystemExit:return True
        if args.command is None:print(HELP);return True
        value=await asyncio.to_thread(dispatch,self.client,args,self.project)
        selected=None if command in {'delete','trash','restore','purge','slack','notion'} else self.client.project(args.project) if hasattr(args,'project') else self.project
        output(value,args,selected)
        if command=='new':await asyncio.to_thread(self.select,value['project_id'])
        if command=='delete' and self.project and self.project['id']==value['project_id']:
            self.project=None;self.seen={};self.toolbar='프로젝트 선택'
        if command=='restore' and self.project is None:await asyncio.to_thread(self.select,value['project_id'])
        return True

    async def run(self):
        from prompt_toolkit import PromptSession
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.patch_stdout import patch_stdout
        from prompt_toolkit.styles import Style
        from prompt_toolkit.completion import WordCompleter
        kb=KeyBindings()
        @kb.add('escape','enter')
        def newline(event):event.current_buffer.insert_text('\n')
        colored=not getattr(self.args,'no_color',False) and 'NO_COLOR' not in os.environ and os.environ.get('TERM')!='dumb'
        style=Style.from_dict({'prompt':'#7bb594','toolbar':'#899c91'}) if colored else Style.from_dict({})
        session=PromptSession(key_bindings=kb,completer=WordCompleter(['/projects','/use','/new','/delete','/trash','/restore','/purge','/status','/history','/tree','/connections','/devices','/target','/auto','/limits','/ask','/next','/restart','/reply','/logs','/report','/notion','/slack','/exit','/quit','/help']),complete_while_typing=False,style=style)
        self.prompt_session=session
        print('/help 도움말 · /exit 종료 (연구 작업은 유지)')
        selector=getattr(self.args,'project',None)
        projects=await asyncio.to_thread(self.client.projects)
        if selector or len(projects)==1:await asyncio.to_thread(self.select,selector)
        else:output(projects,argparse.Namespace(command='projects'))
        with patch_stdout():
            task=asyncio.create_task(self.monitor())
            try:
                while True:
                    try:
                        text=await session.prompt_async([('class:prompt','BrainDance > ')],rprompt=lambda:[('class:toolbar',safe_text(self.toolbar))],reserve_space_for_menu=0)
                        if not await self.handle(text):break
                    except KeyboardInterrupt:continue
                    except EOFError:break
                    except (ClientError,urllib.error.URLError,TimeoutError,OSError,ValueError) as error:print('\n'+safe_text(error))
            finally:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):await task


def main(argv=None):
    args=parser().parse_args(argv)
    if args.command=='monitor':
        try:
            if args.action=='repair-source':
                if not args.source or not args.python:raise ValueError('--source 저장소와 --python 빌드 환경을 지정하세요.')
                from host_repair import build_manifest,register_source
                from brain_monitor import read
                db=getattr(args,'db',default_db())
                current=read(Path(db).parent/'monitor/backend-runtime.json')
                result=register_source(db,build_manifest(args.source,args.python),current.get('image',''),Path.home()/'.local/bin/braindance')
                print(json.dumps(result,ensure_ascii=False));return 0 if result['state']=='registered' else 1
            from brain_monitor import command
            result=command(args.action,getattr(args,'db',default_db()),getattr(args,'server',None) or 'http://127.0.0.1:'+str(getattr(args,'port',None) or 8766),not args.no_notify)
            if getattr(args,'json',False):print(json.dumps(result,ensure_ascii=False))
            else:
                print('BrainDance 감시 · '+('설치됨' if result.get('installed') else '해제됨' if 'installed' in result else '확인 완료')+' · '+('자동 복구 ON · 수리 호출은 기존 연구 사용량에 합산' if result.get('mode')=='auto_recover' else '알림만 · LLM 호출 0회'))
                if result.get('last_check'):print('마지막 확인 '+result['last_check']+' · 활성 연구 '+str(result.get('active_sessions',0))+' · 감지 '+str(len(result.get('findings',[]))))
                for item in result.get('findings',[]):print(safe_text(item['title']+' · '+item['message']))
            return 0
        except (OSError,ValueError) as error:print('BrainDance 감시: '+safe_text(error),file=sys.stderr);return 1
    if args.command=='install-cli':
        try:print(install_launcher());return 0
        except (ClientError,OSError) as error:print('BrainDance: '+safe_text(error),file=sys.stderr);return 1
    if args.command is None and not getattr(args,'no_banner',False) and not getattr(args,'json',False):
        color=sys.stdout.isatty() and not getattr(args,'no_color',False) and 'NO_COLOR' not in os.environ and os.environ.get('TERM')!='dumb'
        print(banner(shutil.get_terminal_size((80,24)).columns,color),flush=True)
    if args.command is None and not sys.stdin.isatty():parser().print_help();return 0
    try:
        client=connect(args)
        if args.command is None:
            try:
                if getattr(args,'plain',False):asyncio.run(Console(client,args).run())
                else:
                    from terminal_ui import ResearchTerminal
                    asyncio.run(ResearchTerminal(client,args).run())
            except ImportError:raise ClientError('대화형 CLI에는 prompt-toolkit이 필요합니다. requirements-cli.txt를 설치하거나 패키지 앱의 braindance 명령을 사용하세요.')
            return 0
        project=None if args.command in {'projects','connections','connection','devices','new','delete','trash','restore','purge','slack','notion'} else client.project(getattr(args,'project',None))
        result=dispatch(client,args,project);output(result,args,project)
        return 1 if (args.command=='chat' and result['state'] in {'failed','interrupted'}) or (args.command=='purge' and result.get('cleanup_pending')) else 0
    except KeyboardInterrupt:
        print('\n연결을 종료했습니다. 서버의 연구 작업은 계속됩니다.',file=sys.stderr);return 130
    except (ClientError,urllib.error.URLError,TimeoutError,OSError,ValueError) as error:
        if getattr(args,'json',False):print(json.dumps(dict(error=safe_text(error)),ensure_ascii=False),file=sys.stderr)
        else:print('BrainDance: '+safe_text(error),file=sys.stderr)
        return 1
