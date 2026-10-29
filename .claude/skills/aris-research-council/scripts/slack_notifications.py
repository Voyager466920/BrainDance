"""Personal Slack DM result notifications; retained reports only, no LLM calls."""
from contextlib import contextmanager
import html
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid

from research_reports import project_data,clean,signature,result_status,quiescent
from tree_store import now


class SlackError(ValueError):
    def __init__(self,message,*,retry_after=0,uncertain=False):
        super().__init__(message);self.retry_after=retry_after;self.uncertain=uncertain


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


class SlackAPI:
    def __init__(self,token):
        if not isinstance(token,str) or not re.fullmatch(r'xoxb-[A-Za-z0-9-]{10,1000}',token):raise ValueError('Slack Bot User OAuth Token(xoxb-)을 확인하세요.')
        self.token=token;self.opener=urllib.request.build_opener(NoRedirect())
    def request(self,method,payload=None):
        if method not in {'auth.test','conversations.open','chat.postMessage'}:raise ValueError('지원하지 않는 Slack 기능입니다.')
        req=urllib.request.Request('https://slack.com/api/'+method,data=json.dumps(payload or {},ensure_ascii=False).encode(),headers={'Authorization':'Bearer '+self.token,'Content-Type':'application/json; charset=utf-8'})
        try:
            with self.opener.open(req,timeout=15) as response:
                header=response.headers.get('X-OAuth-Scopes')
                self.last_scopes=set(v.strip() for v in header.split(',')) if header is not None else None
                data=json.load(response)
        except urllib.error.HTTPError as error:
            if error.code==429:
                try:delay=min(3600,max(1,float((error.headers or {}).get('Retry-After','30'))))
                except ValueError:delay=30
                raise SlackError('Slack 요청 제한 · 자동 재시도 대기',retry_after=delay) from None
            raise SlackError('Slack 요청을 완료하지 못했습니다. HTTP '+str(error.code),uncertain=method=='chat.postMessage' and error.code>=500) from None
        except (OSError,ValueError):raise SlackError('Slack 응답을 확인하지 못했습니다.',uncertain=method=='chat.postMessage') from None
        if not isinstance(data,dict):raise SlackError('Slack 응답 형식을 확인하지 못했습니다.',uncertain=method=='chat.postMessage')
        if not data.get('ok'):
            error=data.get('error','unknown_error')
            messages={'invalid_auth':'Slack 토큰을 확인하세요.','token_revoked':'Slack 토큰이 해제되었습니다.','missing_scope':'봇의 chat:write 및 im:write 권한을 확인하세요.','user_not_found':'본인의 Slack 멤버 ID와 워크스페이스를 확인하세요.','cannot_dm_bot':'봇이 아닌 본인 Slack 멤버 ID를 입력하세요.','account_inactive':'Slack 계정이나 앱이 비활성 상태입니다.'}
            raise SlackError(messages.get(error,'Slack 연결 또는 DM 권한을 확인하세요.'))
        return data


def escape(value,limit=500):
    return html.escape(str(clean(value)),quote=False)[:limit]


def message_for(data,report_url=None):
    brief=data.get('brief') or {};runs=data['runs'];valid=[r for r in runs if r['state']=='succeeded' and r.get('analysis',{}).get('status') in {'measured','compared'}]
    lines=['*결과: '+result_status(data)+'*',escape(data['title'],180),'','*상세 결과*',escape(brief.get('findings') or ('정상 측정 '+str(len(valid))+'회 · 전체 시도 '+str(len(runs))+'회'),850), '*문제*',escape(brief.get('problem') or data.get('goal') or data['title'],600), '*방법*',escape(brief.get('approach') or '자세한 구현과 비교 설정은 연구 보고서에 기록했습니다.',700)]
    if data.get('study_outcome')=='rejected':
        lines[0]='*결과: 실패* · 가설 기각 보고'
        lines[lines.index('*상세 결과*')+1]=escape(data.get('rejection_reason') or brief.get('findings') or '독립 검토에 따라 실험 전에 기각했습니다.',850)+'\n실험 미실행 · 측정 결과 없음'
    for run in valid[-3:]:
        a=run['analysis'];values=(str(a.get('baseline'))+' → '+str(a.get('candidate'))) if a['status']=='compared' else str(a.get('value'))
        lines.append('• '+escape(run['title'],110)+' · '+escape(run['metric'],50)+' '+escape(values,90))
    limits=brief.get('limitations') or ['소규모 실험의 관측 결과이며 신규성·통계적 유의성을 확정하지 않습니다.']
    from quota_guard import describe
    lines.extend(['*한계*',escape(' / '.join(limits[:2]),550),'*남은 사용량*',escape(describe(data.get('account_usage'),data.get('quota_guard')),1400)])
    if data.get('execution_state',{}).get('stop_reason'):lines.extend(['*중지 사유*',escape(data['execution_state']['stop_reason'],600)])
    if report_url and report_url.startswith('https://www.notion.so/'):
        lines.extend(['', '<'+report_url+'|상세 보고서·코드 위치·그래프 보기>'])
    else:lines.extend(['','자세한 내용은 BrainDance 결과 탭의 보고서에서 확인할 수 있습니다.'])
    return dict(text='\n'.join(lines),unfurl_links=False,unfurl_media=False)


class SlackNotifications:
    def __init__(self,store,publications=None,autostart=True):
        self.store=store;self.publications=publications;self.root=Path(store.db_path).parent/'integrations';self.root.mkdir(mode=0o700,exist_ok=True)
        self.db=self.root/'slack.sqlite3';self.secret=self.root/'slack-credentials.json';self.closed=threading.Event();self.lock=threading.RLock()
        with self.connect() as c:
            c.execute('CREATE TABLE IF NOT EXISTS subscriptions(project_id TEXT PRIMARY KEY,enabled INTEGER NOT NULL,since TEXT NOT NULL)')
            c.execute('CREATE TABLE IF NOT EXISTS notification_settings(id INTEGER PRIMARY KEY CHECK(id=1),enabled INTEGER NOT NULL,since TEXT NOT NULL)')
            # Upgrade existing connections once, without replaying other projects' history.
            legacy_enabled=c.execute('SELECT count(*) FROM subscriptions WHERE enabled=1').fetchone()[0]>0
            c.execute('INSERT OR IGNORE INTO notification_settings VALUES(1,?,?)',(int(self.secret.is_file() and legacy_enabled),now()))
            c.execute('''CREATE TABLE IF NOT EXISTS deliveries(id TEXT PRIMARY KEY,project_id TEXT NOT NULL,event_key TEXT NOT NULL UNIQUE,state TEXT NOT NULL,payload TEXT NOT NULL,target TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,retry_at REAL NOT NULL,ts TEXT,error TEXT)''')
            c.execute('CREATE TABLE IF NOT EXISTS session_notifications(id INTEGER PRIMARY KEY CHECK(id=1),since TEXT NOT NULL)')
            c.execute('INSERT OR IGNORE INTO session_notifications VALUES(1,?)',(now(),))
            c.execute("UPDATE deliveries SET state='uncertain',error='이전 전송의 완료 여부를 확인하지 못했습니다. 중복 DM을 방지해 자동 재전송하지 않습니다.' WHERE state='sending'")
        self.thread=threading.Thread(target=self.loop,daemon=True,name='braindance-slack')
        if autostart:self.thread.start()
    @contextmanager
    def connect(self):
        c=sqlite3.connect(self.db,timeout=15);c.row_factory=sqlite3.Row
        try:
            with c:yield c
        finally:c.close()
    def credentials(self):return json.loads(self.secret.read_text()) if self.secret.is_file() else {}
    def settings(self):
        with self.connect() as c:return dict(c.execute('SELECT enabled,since FROM notification_settings WHERE id=1').fetchone())
    def configure(self,project_id=None,member_id=None,token='',enabled=True):
        # project_id remains accepted for older clients; the connection is global.
        if not re.fullmatch(r'[UW][A-Z0-9]{8,24}',member_id or ''):raise ValueError('본인 Slack 멤버 ID(U로 시작)를 입력하세요.')
        if type(enabled) is not bool:raise ValueError('자동 결과 알림 설정을 확인하세요.')
        with self.lock:
            old=self.credentials();token=token or old.get('token','');api=SlackAPI(token);auth=api.request('auth.test')
            if auth.get('user_id')==member_id:raise ValueError('봇 ID 대신 본인의 Slack 멤버 ID를 입력하세요.')
            channel=api.request('conversations.open',dict(users=member_id))['channel']['id']
            if not re.fullmatch(r'D[A-Z0-9]{8,24}',channel):raise ValueError('개인 DM 채널을 확인하지 못했습니다.')
            record=dict(token=token,member_id=member_id,channel=channel,team=auth.get('team'),team_id=auth.get('team_id'),bot_user_id=auth.get('user_id'))
            fd,name=tempfile.mkstemp(dir=self.root,prefix='.slack-');os.fchmod(fd,0o600)
            with os.fdopen(fd,'w') as stream:json.dump(record,stream)
            os.replace(name,self.secret)
            target_changed=(old.get('team_id'),old.get('channel'))!=(record.get('team_id'),channel)
            if target_changed or not enabled:
                with self.connect() as c:c.execute("UPDATE deliveries SET state='cancelled',error='DM 연결 대상이 변경되었습니다.' WHERE state='queued'")
            settings=self.settings();since=now() if target_changed or not settings['enabled'] else settings['since']
            with self.connect() as c:c.execute('UPDATE notification_settings SET enabled=?,since=? WHERE id=1',(int(enabled),since))
        return self.state()
    def state(self,project_id=None):
        data=self.credentials()
        with self.connect() as c:
            settings=c.execute('SELECT enabled,since FROM notification_settings WHERE id=1').fetchone();rows=c.execute('SELECT id,project_id,event_key,state,created_at,ts,error FROM deliveries ORDER BY rowid DESC LIMIT 8').fetchall()
        return dict(connected=bool(data),enabled=bool(data and settings['enabled']),scope='all_projects',since=settings['since'],member_id=data.get('member_id'),workspace=data.get('team'),deliveries=[dict(r) for r in rows])
    def disconnect(self):
        with self.lock:
            self.secret.unlink(missing_ok=True)
            with self.connect() as c:
                c.execute('UPDATE subscriptions SET enabled=0');c.execute('UPDATE notification_settings SET enabled=0 WHERE id=1');c.execute("UPDATE deliveries SET state='cancelled' WHERE state='queued'")
        return dict(connected=False)
    def enqueue(self,project_id,event_key,test=False,job=None):
        with self.connect() as c:prior=c.execute('SELECT id,state FROM deliveries WHERE event_key=?',(event_key,)).fetchone()
        if prior:return dict(prior)
        if type(test) is not bool:raise ValueError('DM 테스트 설정을 확인하세요.')
        if not test and not project_id:raise ValueError('결과를 보낼 프로젝트를 선택하세요. Slack 연결·테스트에는 프로젝트가 필요하지 않습니다.')
        data=project_data(self.store,project_id) if not test else None;project_digest=signature(data) if data else None;creds=self.credentials()
        if job and not test:
            folder=Path(job['run_dir'])
            if not folder.resolve().is_relative_to((Path(self.store.db_path).parent/'council-runs').resolve()):raise ValueError('관리되는 연구 보고서가 아닙니다.')
            done=json.loads((folder/'native-completion.json').read_text())
            if done.get('job_id')!=job['id']:raise ValueError('연구 보고서의 작업 식별자가 다릅니다.')
            selected=next((n for n in data['nodes'] if n['id']==job['node_id']),None)
            if selected:
                data={**data,'title':data['title']+' · '+selected['title'],'goal':selected['title'],'nodes':[selected],'runs':[r for r in data['runs'] if r['id'] in done.get('run_ids',[])],'study_reports':[s for s in data.get('study_reports',[]) if s['node_id']==selected['id']],'brief':{},'study_outcome':done.get('outcome'),'rejection_reason':done.get('reason')}
                brief=folder/'research-brief.json'
                if brief.is_file() and not brief.is_symlink():
                    from research_reports import validate_brief
                    data['brief']=validate_brief(json.loads(brief.read_text()))
        if data and getattr(self,'quota_snapshot',None):
            from quota_guard import snapshot
            value=snapshot(self.quota_snapshot())
            if value['providers']:data['account_usage']=value
        if not creds:raise ValueError('먼저 /slack에서 개인 DM 연결을 등록하세요.')
        url=None;wait_for_report=False
        if self.publications and not test:
            state=self.publications.state(project_id)
            url=next((j.get('page_url') for j in state['jobs'] if j['state']=='completed' and j.get('page_url') and j.get('digest')==project_digest),None)
            if not test and not url and state.get('connected') and (state.get('link') or {}).get('auto_sync'):
                self.publications.enqueue(project_id,True);wait_for_report=True
        identity=str(uuid.uuid4());payload=dict(text='BrainDance 개인 DM 연결 테스트입니다. 모든 프로젝트의 새 연구 결과를 이 DM으로 받습니다. 연구는 자동으로 재개되지 않습니다.',unfurl_links=False,unfurl_media=False,_connection_test=True) if test else message_for(data,url);payload.update(channel=creds['channel'])
        if wait_for_report:payload.update(_report_digest=project_digest,_await_notion=True)
        with self.connect() as c:
            c.execute('INSERT OR IGNORE INTO deliveries VALUES(?,?,?,?,?,?,?,?,?,?,?)',(identity,'' if test else project_id,event_key,'queued',json.dumps(payload,ensure_ascii=False),creds['channel'],now(),now(),0,None,None))
            return dict(c.execute('SELECT id,state FROM deliveries WHERE event_key=?',(event_key,)).fetchone())
    def enqueue_remote(self,project_id,event_key,text,thread_ts,generation):
        creds=self.credentials()
        if not creds:raise ValueError('Slack 봇 연결이 없습니다.')
        payload=dict(channel=creds['channel'],text=escape(text,6500),thread_ts=thread_ts,unfurl_links=False,unfurl_media=False,_remote_reply=True,_remote_generation=generation)
        identity=str(uuid.uuid4())
        with self.connect() as c:
            c.execute('INSERT OR IGNORE INTO deliveries VALUES(?,?,?,?,?,?,?,?,?,?,?)',(identity,project_id or '',event_key,'queued',json.dumps(payload,ensure_ascii=False),creds['channel'],now(),now(),0,None,None))
            return dict(c.execute('SELECT id,state FROM deliveries WHERE event_key=?',(event_key,)).fetchone())

    def tick(self):
        settings=self.settings()
        if not self.credentials() or not settings['enabled']:return
        with self.store._connect() as c:jobs=[dict(r) for r in c.execute("""SELECT j.id,j.project_id,j.node_id,j.run_dir,j.config,j.finished_at
            FROM research_jobs j JOIN projects p ON p.id=j.project_id LEFT JOIN project_lifecycle l ON l.project_id=p.id
            WHERE l.deleted_at IS NULL AND j.state='completed' AND j.phase='native-completed' AND j.finished_at>=?
            ORDER BY j.finished_at,j.rowid""",(settings['since'],))]
        for job in jobs:
            try:
                if json.loads(job['config']).get('task_role')=='discovery':continue
                self.enqueue(job['project_id'],'study:'+job['id'],job=job)
            except (ValueError,KeyError,OSError):continue
        with self.connect() as c:since=c.execute('SELECT since FROM session_notifications WHERE id=1').fetchone()[0]
        with self.store._connect() as c:
            sessions=[dict(r) for r in c.execute("SELECT id,project_id,status,updated_at,config FROM automatic_sessions WHERE status IN ('stopped','completed') AND updated_at>=? ORDER BY updated_at",(max(since,settings['since']),))]
        for session in sessions:
            try:
                if quiescent(self.store,session['project_id']):
                    count=json.loads(session['config']).get('continuation_count',0)
                    key='session:'+session['id']+':'+session['status']+(':continuation:'+str(count) if count else '')
                    self.enqueue(session['project_id'],key)
            except (ValueError,KeyError,OSError):continue

    def process(self,row):
        with self.lock:
            creds=self.credentials()
            if not creds or creds['channel']!=row['target']:
                with self.connect() as c:c.execute("UPDATE deliveries SET state='cancelled',error='Slack 연결 대상이 변경되었습니다.' WHERE id=?",(row['id'],))
                return
            payload=json.loads(row['payload'])
            connection_test=payload.get('_connection_test',False);remote=payload.get('_remote_reply',False)
            if remote and not getattr(self,'remote_reply_guard',lambda value:False)(payload.get('_remote_generation')):
                with self.connect() as c:c.execute("UPDATE deliveries SET state='cancelled',error='DM 지시 연결이 변경되었습니다.' WHERE id=?",(row['id'],))
                return
            if not connection_test and not remote and not self.settings()['enabled']:
                with self.connect() as c:c.execute("UPDATE deliveries SET state='cancelled',error='전체 프로젝트 자동 알림이 꺼졌습니다.' WHERE id=?",(row['id'],))
                return
            if not connection_test and (not remote or row['project_id']):
                try:project_data(self.store,row['project_id'])
                except (ValueError,KeyError):
                    with self.connect() as c:c.execute("UPDATE deliveries SET state='cancelled',error='프로젝트 기록을 확인할 수 없어 알림을 중지했습니다.',updated_at=? WHERE id=?",(now(),row['id']))
                    return
            if payload.get('_await_notion') and self.publications:
                from datetime import datetime,timezone
                state=self.publications.state(row['project_id'])
                url=next((j.get('page_url') for j in state['jobs'] if j['state']=='completed' and j.get('digest')==payload['_report_digest'] and j.get('page_url')),None)
                if url:
                    for footer in ['전체 보고서·코드 위치·그래프는 BrainDance 결과 탭에 보존했습니다.','자세한 내용은 BrainDance 결과 탭의 보고서에서 확인할 수 있습니다.']:payload['text']=payload['text'].replace(footer,'<'+url+'|상세 보고서 보기>')
                elif (datetime.now(timezone.utc)-datetime.fromisoformat(row['created_at'])).total_seconds()<180:
                    with self.connect() as c:c.execute('UPDATE deliveries SET retry_at=? WHERE id=?',(time.time()+5,row['id']))
                    return
            payload={k:v for k,v in payload.items() if not k.startswith('_')}
            with self.connect() as c:c.execute("UPDATE deliveries SET state='sending',updated_at=? WHERE id=?",(now(),row['id']))
            try:
                response=SlackAPI(creds['token']).request('chat.postMessage',payload)
                with self.connect() as c:c.execute("UPDATE deliveries SET state='sent',ts=?,updated_at=?,error=NULL WHERE id=?",(response['ts'],now(),row['id']))
                if row['project_id'] and getattr(self,'on_sent',None):
                    try:self.on_sent(response['ts'],row['project_id'])
                    except Exception:pass # The durable delivery receipt also resolves thread ownership.
            except ValueError as error:
                if not isinstance(error,SlackError):
                    with self.connect() as c:c.execute("UPDATE deliveries SET state='cancelled',error='프로젝트 기록을 확인할 수 없어 알림을 중지했습니다.',updated_at=? WHERE id=?",(now(),row['id']))
                    return

                state='uncertain' if error.uncertain else 'queued' if error.retry_after else 'failed'
                with self.connect() as c:c.execute('UPDATE deliveries SET state=?,retry_at=?,error=?,updated_at=? WHERE id=?',(state,time.time()+error.retry_after,str(error),now(),row['id']))
    def loop(self):
        while not self.closed.wait(3):
            try:
                self.tick()
                with self.connect() as c:row=c.execute("SELECT * FROM deliveries WHERE state='queued' AND retry_at<=? ORDER BY rowid LIMIT 1",(time.time(),)).fetchone()
                if row:self.process(dict(row))
            except (ValueError,KeyError,OSError,sqlite3.Error):pass
    def close(self):
        self.closed.set()
        if self.thread.is_alive():self.thread.join(timeout=18)
