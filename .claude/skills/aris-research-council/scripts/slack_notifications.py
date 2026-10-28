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

from research_reports import project_data,clean,signature
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
            with self.opener.open(req,timeout=15) as response:data=json.load(response)
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
    lines=['*BrainDance 연구 결과*',escape(data['title'],180),'', '*문제*',escape(brief.get('problem') or data.get('goal') or data['title'],600), '*방법*',escape(brief.get('approach') or '자세한 구현과 비교 설정은 연구 보고서에 기록했습니다.',700),'*결과*',escape(brief.get('findings') or ('정상 측정 '+str(len(valid))+'회 · 전체 시도 '+str(len(runs))+'회'),850)]
    for run in valid[-3:]:
        a=run['analysis'];values=(str(a.get('baseline'))+' → '+str(a.get('candidate'))) if a['status']=='compared' else str(a.get('value'))
        lines.append('• '+escape(run['title'],110)+' · '+escape(run['metric'],50)+' '+escape(values,90))
    limits=brief.get('limitations') or ['소규모 실험의 관측 결과이며 신규성·통계적 유의성을 확정하지 않습니다.']
    lines.extend(['*한계*',escape(' / '.join(limits[:2]),550)])
    if report_url and report_url.startswith('https://www.notion.so/'):
        lines.extend(['', '<'+report_url+'|상세 보고서·코드 위치·그래프 보기>'])
    else:lines.extend(['','전체 보고서·코드 위치·그래프는 BrainDance 결과 탭에 보존했습니다.'])
    return dict(text='\n'.join(lines),unfurl_links=False,unfurl_media=False)


class SlackNotifications:
    def __init__(self,store,publications=None,autostart=True):
        self.store=store;self.publications=publications;self.root=Path(store.db_path).parent/'integrations';self.root.mkdir(mode=0o700,exist_ok=True)
        self.db=self.root/'slack.sqlite3';self.secret=self.root/'slack-credentials.json';self.closed=threading.Event();self.lock=threading.RLock()
        with self.connect() as c:
            c.execute('CREATE TABLE IF NOT EXISTS subscriptions(project_id TEXT PRIMARY KEY,enabled INTEGER NOT NULL,since TEXT NOT NULL)')
            c.execute('''CREATE TABLE IF NOT EXISTS deliveries(id TEXT PRIMARY KEY,project_id TEXT NOT NULL,event_key TEXT NOT NULL UNIQUE,state TEXT NOT NULL,payload TEXT NOT NULL,target TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,retry_at REAL NOT NULL,ts TEXT,error TEXT)''')
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
    def configure(self,project_id,member_id,token='',enabled=True):
        project_data(self.store,project_id)
        if not re.fullmatch(r'[UW][A-Z0-9]{8,24}',member_id or ''):raise ValueError('본인 Slack 멤버 ID(U로 시작)를 입력하세요.')
        with self.lock:
            old=self.credentials();token=token or old.get('token','');api=SlackAPI(token);auth=api.request('auth.test')
            if auth.get('user_id')==member_id:raise ValueError('봇 ID 대신 본인의 Slack 멤버 ID를 입력하세요.')
            channel=api.request('conversations.open',dict(users=member_id))['channel']['id']
            if not re.fullmatch(r'D[A-Z0-9]{8,24}',channel):raise ValueError('개인 DM 채널을 확인하지 못했습니다.')
            record=dict(token=token,member_id=member_id,channel=channel,team=auth.get('team'),team_id=auth.get('team_id'))
            fd,name=tempfile.mkstemp(dir=self.root,prefix='.slack-');os.fchmod(fd,0o600)
            with os.fdopen(fd,'w') as stream:json.dump(record,stream)
            os.replace(name,self.secret)
            if old.get('channel') and old['channel']!=channel:
                with self.connect() as c:c.execute("UPDATE deliveries SET state='cancelled',error='DM 연결 대상이 변경되었습니다.' WHERE state='queued'")
            with self.connect() as c:c.execute('INSERT INTO subscriptions VALUES(?,?,?) ON CONFLICT(project_id) DO UPDATE SET enabled=excluded.enabled',(project_id,int(enabled),now()))
        return self.state(project_id)
    def state(self,project_id):
        data=self.credentials()
        with self.connect() as c:
            sub=c.execute('SELECT * FROM subscriptions WHERE project_id=?',(project_id,)).fetchone();rows=c.execute('SELECT id,event_key,state,created_at,ts,error FROM deliveries WHERE project_id=? ORDER BY rowid DESC LIMIT 8',(project_id,)).fetchall()
        return dict(connected=bool(data),enabled=bool(sub and sub['enabled']),member_id=data.get('member_id'),workspace=data.get('team'),deliveries=[dict(r) for r in rows])
    def disconnect(self):
        with self.lock:
            self.secret.unlink(missing_ok=True)
            with self.connect() as c:c.execute('UPDATE subscriptions SET enabled=0');c.execute("UPDATE deliveries SET state='cancelled' WHERE state='queued'")
        return dict(connected=False)
    def enqueue(self,project_id,event_key,test=False,job=None):
        with self.connect() as c:prior=c.execute('SELECT id,state FROM deliveries WHERE event_key=?',(event_key,)).fetchone()
        if prior:return dict(prior)
        data=project_data(self.store,project_id);project_digest=signature(data);creds=self.credentials()
        if job:
            folder=Path(job['run_dir'])
            if not folder.resolve().is_relative_to((Path(self.store.db_path).parent/'council-runs').resolve()):raise ValueError('관리되는 연구 보고서가 아닙니다.')
            done=json.loads((folder/'native-completion.json').read_text())
            if done.get('job_id')!=job['id']:raise ValueError('연구 보고서의 작업 식별자가 다릅니다.')
            selected=next((n for n in data['nodes'] if n['id']==job['node_id']),None)
            if selected:
                data={**data,'title':data['title']+' · '+selected['title'],'goal':selected['title'],'nodes':[selected],'runs':[r for r in data['runs'] if r['id'] in done.get('run_ids',[])],'brief':{}}
                brief=folder/'research-brief.json'
                if brief.is_file() and not brief.is_symlink():
                    from research_reports import validate_brief
                    data['brief']=validate_brief(json.loads(brief.read_text()))
        if not creds:raise ValueError('먼저 /slack에서 개인 DM 연결을 등록하세요.')
        url=None;wait_for_report=False
        if self.publications:
            state=self.publications.state(project_id)
            url=next((j.get('page_url') for j in state['jobs'] if j['state']=='completed' and j.get('page_url') and j.get('digest')==project_digest),None)
            if not test and not url and state.get('connected') and (state.get('link') or {}).get('auto_sync'):
                self.publications.enqueue(project_id,True);wait_for_report=True
        identity=str(uuid.uuid4());payload=dict(text='BrainDance 개인 DM 연결 테스트입니다. 연구는 자동으로 재개되지 않습니다.',unfurl_links=False,unfurl_media=False) if test else message_for(data,url);payload.update(channel=creds['channel'])
        if wait_for_report:payload.update(_report_digest=project_digest,_await_notion=True)
        with self.connect() as c:
            c.execute('INSERT OR IGNORE INTO deliveries VALUES(?,?,?,?,?,?,?,?,?,?,?)',(identity,project_id,event_key,'queued',json.dumps(payload,ensure_ascii=False),creds['channel'],now(),now(),0,None,None))
            return dict(c.execute('SELECT id,state FROM deliveries WHERE event_key=?',(event_key,)).fetchone())
    def tick(self):
        if not self.credentials():return
        with self.connect() as c:subs=[dict(r) for r in c.execute('SELECT * FROM subscriptions WHERE enabled=1')]
        for sub in subs:
            try:
                project_data(self.store,sub['project_id'])
                with self.store._connect() as c:jobs=[dict(r) for r in c.execute("SELECT id,node_id,run_dir,config,finished_at FROM research_jobs WHERE project_id=? AND state='completed' AND phase='native-completed' AND finished_at>=?",(sub['project_id'],sub['since']))]
                for job in jobs:
                    if json.loads(job['config']).get('task_role')=='discovery':continue
                    self.enqueue(sub['project_id'],'study:'+job['id'],job=job)
            except (ValueError,KeyError):continue
    def process(self,row):
        with self.lock:
            creds=self.credentials()
            if not creds or creds['channel']!=row['target']:
                with self.connect() as c:c.execute("UPDATE deliveries SET state='cancelled',error='Slack 연결 대상이 변경되었습니다.' WHERE id=?",(row['id'],))
                return
            payload=json.loads(row['payload'])
            if payload.get('_await_notion') and self.publications:
                from datetime import datetime,timezone
                state=self.publications.state(row['project_id'])
                url=next((j.get('page_url') for j in state['jobs'] if j['state']=='completed' and j.get('digest')==payload['_report_digest'] and j.get('page_url')),None)
                if url:payload['text']=payload['text'].replace('전체 보고서·코드 위치·그래프는 BrainDance 결과 탭에 보존했습니다.','<'+url+'|상세 보고서·코드 위치·그래프 보기>')
                elif (datetime.now(timezone.utc)-datetime.fromisoformat(row['created_at'])).total_seconds()<180:
                    with self.connect() as c:c.execute('UPDATE deliveries SET retry_at=? WHERE id=?',(time.time()+5,row['id']))
                    return
            payload={k:v for k,v in payload.items() if not k.startswith('_')}
            with self.connect() as c:c.execute("UPDATE deliveries SET state='sending',updated_at=? WHERE id=?",(now(),row['id']))
            try:
                project_data(self.store,row['project_id']);response=SlackAPI(creds['token']).request('chat.postMessage',payload)
                with self.connect() as c:c.execute("UPDATE deliveries SET state='sent',ts=?,updated_at=?,error=NULL WHERE id=?",(response['ts'],now(),row['id']))
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
