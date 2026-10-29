"""Owner-only Slack DM transport for the existing project conversation/controller.

Socket Mode authenticates delivery. Host code additionally binds workspace, owner,
bot and DM; no HTTP event receiver or model-authored control parameters are used.
"""
import hashlib
import html
import json
import logging
import math
import os
from pathlib import Path
import re
import ssl
import tempfile
import threading
import time
import uuid

from slack_notifications import SlackAPI
from tree_store import now

HELP='''BrainDance 개인 DM 지시
프로젝트 목록
프로젝트 선택 <이름 또는 짧은 ID>
상태 / 사용량 / 중지 / 일시정지
재개 2시간 사용량 10%p
재개 2시간 보호 끄기
그 밖의 자연어 질문·연구 지시는 같은 프로젝트 대화로 이어집니다.
프로젝트를 바꿔도 기존 대화 묶음은 원래 프로젝트를 유지합니다.'''
TOKEN=re.compile(r'\b(?:xapp-|xox[bap]-|sk-ant-|sk-proj-)[A-Za-z0-9-]{10,}')


def target_key(creds):
    return hashlib.sha256(json.dumps([creds.get(k) for k in ['team_id','member_id','channel']],separators=(',',':')).encode()).hexdigest()


def socket_client(app_token,bot_token):
    import certifi
    from slack_sdk.web import WebClient
    from slack_sdk.socket_mode import SocketModeClient
    logger=logging.getLogger('braindance.slack.socket');logger.handlers=[logging.NullHandler()];logger.propagate=False;logger.setLevel(logging.CRITICAL);logger.disabled=True
    web=WebClient(token=bot_token,ssl=ssl.create_default_context(cafile=certifi.where()),timeout=12,logger=logger,retry_handlers=[])
    return SocketModeClient(app_token=app_token,web_client=web,logger=logger,concurrency=1,trace_enabled=False,all_message_trace_enabled=False)


def validate_app(app_token,bot_token):
    client=socket_client(app_token,bot_token)
    try:
        value=client.web_client.apps_connections_open(app_token=app_token)
        if not value.get('ok') or not str(value.get('url','')).startswith('wss://'):raise ValueError('Slack App-Level Token 또는 Socket Mode 설정을 확인하세요.')
    except Exception:raise ValueError('Slack App-Level Token(xapp-)과 connections:write 권한, Socket Mode 설정을 확인하세요.') from None
    finally:client.close()


class SlackRemote:
    def __init__(self,store,notifications,chat,controller,quota_status=None,autostart=True):
        self.store,self.notifications,self.chat,self.controller=store,notifications,chat,controller
        self.quota_status=quota_status;self.secret=notifications.root/'slack-remote-credentials.json'
        self.closed=threading.Event();self.lock=threading.RLock();self.client=None;self.transport_generation=None
        self.connection='disabled';self.error=None;self.last_event_at=None
        with self.db() as c:
            c.execute('CREATE TABLE IF NOT EXISTS remote_settings(id INTEGER PRIMARY KEY CHECK(id=1),enabled INTEGER NOT NULL,project_id TEXT,generation TEXT NOT NULL)')
            c.execute('INSERT OR IGNORE INTO remote_settings VALUES(1,0,NULL,?)',(str(uuid.uuid4()),))
            c.execute('''CREATE TABLE IF NOT EXISTS remote_events (
                id TEXT PRIMARY KEY,event_id TEXT NOT NULL,team_id TEXT NOT NULL,event_ts TEXT NOT NULL,thread_ts TEXT NOT NULL,
                text TEXT NOT NULL,digest TEXT NOT NULL,generation TEXT NOT NULL,project_id TEXT,state TEXT NOT NULL,
                chat_id TEXT,response TEXT,reply_queued INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL,updated_at TEXT NOT NULL)''')
            c.execute('CREATE TABLE IF NOT EXISTS remote_threads(thread_ts TEXT NOT NULL,target_key TEXT NOT NULL,project_id TEXT NOT NULL,PRIMARY KEY(thread_ts,target_key))')
            # A crash after dispatch cannot authorize replay of a time/budget change.
            rows=c.execute("SELECT * FROM remote_events WHERE state='processing'").fetchall()
            for row in rows:
                with store._connect() as local:answer=local.execute("SELECT id FROM research_chat WHERE request_id=? AND role='assistant'",(self.request_id(row['id']),)).fetchone()
                if answer:c.execute("UPDATE remote_events SET state='waiting_reply',chat_id=? WHERE id=?",(answer['id'],row['id']))
                else:c.execute("UPDATE remote_events SET state='uncertain',response=? WHERE id=?",('이전 지시의 완료 여부를 확인하지 못해 자동으로 반복하지 않았습니다. 상태를 확인한 뒤 필요하면 다시 지시하세요.',row['id']))
        notifications.remote_reply_guard=self.active
        notifications.on_sent=self.bind_thread
        self.thread=threading.Thread(target=self.loop,daemon=True,name='braindance-slack-commands')
        self.socket_thread=threading.Thread(target=self.socket_loop,daemon=True,name='braindance-slack-socket')
        if autostart:self.thread.start();self.socket_thread.start()

    def db(self):return self.notifications.connect()
    def credentials(self):return json.loads(self.secret.read_text()) if self.secret.is_file() else {}
    def settings(self):
        with self.db() as c:return dict(c.execute('SELECT * FROM remote_settings WHERE id=1').fetchone())
    @staticmethod
    def request_id(identity):return 'slack-'+hashlib.sha256(identity.encode()).hexdigest()
    def active(self,generation=None):
        settings=self.settings();creds=self.notifications.credentials();remote=self.credentials()
        return bool(not self.closed.is_set() and settings['enabled'] and creds and remote and remote.get('target_key')==target_key(creds) and (generation is None or generation==settings['generation']))
    def state(self):
        settings=self.settings();title=None
        if settings['project_id']:
            title=next((p['title'] for p in self.projects() if p['id']==settings['project_id']),None)
        try:
            from slack_sdk.socket_mode import SocketModeClient
            available=SocketModeClient is not None
        except ImportError:available=False
        return dict(enabled=bool(settings['enabled']),configured=self.secret.is_file(),connection=self.connection if self.active() else 'disabled',error=self.error,project_id=settings['project_id'],project_title=title,last_event_at=self.last_event_at,sdk_available=available,scope='registered_owner_dm_only')

    def configure(self,app_token='',enabled=True):
        if type(enabled) is not bool:raise ValueError('DM 지시 수신 설정을 확인하세요.')
        if not enabled:return self.disable()
        creds=self.notifications.credentials()
        if not creds:raise ValueError('먼저 /slack에서 본인 DM 봇 연결을 등록하세요.')
        app_token=app_token or self.credentials().get('app_token','')
        if not re.fullmatch(r'xapp-[A-Za-z0-9-]{10,1000}',app_token):raise ValueError('App-Level Token(xapp-)을 숨김 입력으로 등록하세요.')
        api=SlackAPI(creds['token']);auth=api.request('auth.test')
        if auth.get('team_id')!=creds.get('team_id') or not auth.get('user_id') or auth['user_id']==creds['member_id']:raise ValueError('기존 Slack 봇과 워크스페이스를 확인하세요.')
        scopes=getattr(api,'last_scopes',None)
        if scopes is not None and 'im:history' not in scopes:raise ValueError('Slack 앱에 im:history 권한과 message.im 이벤트를 추가하고 워크스페이스에 다시 설치하세요.')
        validate_app(app_token,creds['token'])
        value=dict(app_token=app_token,target_key=target_key(creds),bot_user_id=auth['user_id'])
        changed=self.credentials().get('target_key')!=value['target_key']
        with self.lock:
            fd,name=tempfile.mkstemp(dir=self.notifications.root,prefix='.slack-remote-');os.fchmod(fd,0o600)
            with os.fdopen(fd,'w') as stream:json.dump(value,stream)
            os.replace(name,self.secret)
            with self.db() as c:
                c.execute('UPDATE remote_settings SET enabled=1,generation=? WHERE id=1',(str(uuid.uuid4()),))
                if changed:c.execute('UPDATE remote_settings SET project_id=NULL WHERE id=1')
                c.execute("UPDATE remote_events SET state='cancelled' WHERE state IN ('pending','waiting_reply')")
            self.connection='connecting';self.error=None
        return self.state()

    def disable(self,forget=False):
        with self.db() as c:
            c.execute('UPDATE remote_settings SET enabled=0,generation=? WHERE id=1',(str(uuid.uuid4()),))
            c.execute("UPDATE remote_events SET state='cancelled' WHERE state IN ('pending','waiting_reply')")
        if forget:self.secret.unlink(missing_ok=True)
        self.connection='disabled'
        self.close_client()
        return self.state()

    def receive(self,payload):
        if not self.active() or not isinstance(payload,dict) or payload.get('type')!='event_callback':return False
        creds=self.notifications.credentials();remote=self.credentials();event=payload.get('event') or {}
        if not isinstance(event,dict):return False
        if payload.get('team_id')!=creds['team_id'] or payload.get('is_ext_shared_channel'):return False
        if event.get('type')!='message' or event.get('channel_type')!='im' or event.get('channel')!=creds['channel'] or event.get('user')!=creds['member_id']:return False
        if event.get('subtype') is not None or event.get('bot_id') or event.get('hidden'):return False
        authorizations=payload.get('authorizations') or []
        if not isinstance(authorizations,list):return False
        if not any(isinstance(a,dict) and a.get('user_id')==remote.get('bot_user_id') and a.get('is_bot') is True and a.get('team_id')==creds['team_id'] for a in authorizations):return False
        event_id=payload.get('event_id');stamp=event.get('ts');thread=event.get('thread_ts') or stamp;text=event.get('text')
        if not isinstance(event_id,str) or not re.fullmatch(r'Ev[A-Za-z0-9-]{2,100}',event_id):return False
        if not all(isinstance(v,str) and re.fullmatch(r'\d{1,20}\.\d{1,12}',v) for v in [stamp,thread]):return False
        if not isinstance(text,str) or not text.strip():return False
        text=html.unescape(text).strip();digest=hashlib.sha256(json.dumps([text,stamp,thread],ensure_ascii=False).encode()).hexdigest()
        if TOKEN.search(text):text='[연결 토큰 입력 차단]'
        elif len(text)>6000:text='[메시지 길이 제한]'
        identity=creds['team_id']+':'+event_id;settings=self.settings()
        with self.db() as c:
            old=c.execute('SELECT digest FROM remote_events WHERE id=?',(identity,)).fetchone()
            if old:return old['digest']==digest
            c.execute('INSERT INTO remote_events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(identity,event_id,creds['team_id'],stamp,thread,text,digest,settings['generation'],None,'pending',None,None,0,now(),now()))
        self.last_event_at=now();return True

    def on_socket(self,client,request):
        # Persist a small authenticated event before ACK; dispatch/model work happens elsewhere.
        if request.type=='events_api':self.receive(request.payload)
        from slack_sdk.socket_mode.response import SocketModeResponse
        client.send_socket_mode_response(SocketModeResponse(envelope_id=request.envelope_id))

    def projects(self):return [p for p in self.store.export_json()['projects'] if not p.get('deleted_at')]
    def bind_thread(self,stamp,project_id):
        creds=self.notifications.credentials()
        if not creds:return
        with self.db() as c:c.execute('INSERT OR IGNORE INTO remote_threads VALUES(?,?,?)',(stamp,target_key(creds),project_id))
    def thread_project(self,stamp):
        creds=self.notifications.credentials()
        with self.db() as c:
            bound=c.execute('SELECT project_id FROM remote_threads WHERE thread_ts=? AND target_key=?',(stamp,target_key(creds))).fetchone()
            if not bound:bound=c.execute("SELECT project_id FROM deliveries WHERE ts=? AND target=? AND state='sent' AND project_id!='' AND created_at>=?",(stamp,creds['channel'],self.notifications.settings()['since'])).fetchone()
        return bound['project_id'] if bound else None
    def project_for(self,event):
        bound=self.thread_project(event['thread_ts'])
        if bound:return bound
        if event['thread_ts']!=event['event_ts']:raise ValueError('이 대화 묶음의 프로젝트를 확인할 수 없습니다. 새 DM으로 프로젝트 선택 <이름>을 보내세요.')
        return self.settings()['project_id']

    def record(self,event,project_id,text):
        root=self.controller.root(project_id)
        origin=dict(kind='slack_dm',event_id=event['event_id'],thread_ts=event['thread_ts'],member_id=self.notifications.credentials()['member_id'])
        return self.chat.send(dict(node_id=root['id'],content=event['text'],mode='ask',request_id=self.request_id(event['id'])),origin=origin,direct_reply=dict(reply=text))
    def finish(self,event,text,project_id=None):
        if project_id:self.record(event,project_id,text)
        with self.db() as c:c.execute("UPDATE remote_events SET state='completed',project_id=?,response=?,updated_at=? WHERE id=?",(project_id,text,now(),event['id']))

    def dispatch(self,event):
        if not self.active(event['generation']):
            with self.db() as c:c.execute("UPDATE remote_events SET state='cancelled' WHERE id=?",(event['id'],))
            return
        with self.db() as c:
            if c.execute("UPDATE remote_events SET state='processing' WHERE id=? AND state='pending'",(event['id'],)).rowcount!=1:return
        project_id=None
        try:
            text=event['text'].strip();lower=text.lower();compact=re.sub(r'\s+','',lower).rstrip('!.')
            if text=='[메시지 길이 제한]':self.finish(event,'메시지는 6000자 이하로 나눠 보내세요. 긴 원문은 저장하거나 모델에 전달하지 않았습니다.');return
            if text=='[연결 토큰 입력 차단]':self.finish(event,'토큰은 Slack·연구 대화에 등록하지 않습니다. BrainDance의 /slack 숨김 입력을 사용하세요.');return
            if compact in {'도움말','help','연결확인'}:self.finish(event,HELP);return
            if compact in {'프로젝트목록','projects','프로젝트'}:
                listing='\n'.join('• '+p['title']+' ['+p['id'][:8]+']' for p in self.projects()) or '프로젝트가 없습니다. 로컬 CLI에서 먼저 만들어 주세요.'
                self.finish(event,listing+'\n\n프로젝트 선택 <이름 또는 짧은 ID>');return
            select=re.fullmatch(r'(?:프로젝트\s*(?:선택|변경)|project)\s+(.+)',text,re.I)
            if select:
                selector=select[1].strip();rows=[p for p in self.projects() if p['title'].casefold()==selector.casefold() or len(selector)>=6 and p['id'].startswith(selector)]
                if len(rows)!=1:raise ValueError('프로젝트를 하나로 선택할 수 없습니다. 프로젝트 목록의 이름이나 짧은 ID를 사용하세요.')
                selected_id=rows[0]['id']
                if event['thread_ts']!=event['event_ts']:
                    old=self.thread_project(event['thread_ts'])
                    if old and old!=selected_id:
                        project_id=old;raise ValueError('기존 대화 묶음의 프로젝트는 바꾸지 않습니다. 새 DM으로 프로젝트를 선택하세요.')
                project_id=selected_id
                with self.db() as c:c.execute('UPDATE remote_settings SET project_id=? WHERE id=1',(project_id,))
                self.bind_thread(event['thread_ts'],project_id);self.finish(event,'선택한 프로젝트: '+rows[0]['title']+'\n이 DM의 새 지시는 같은 프로젝트 대화에 기록합니다.',project_id);return
            project_id=self.project_for(event)
            if not project_id:raise ValueError('먼저 프로젝트 목록을 보고 프로젝트 선택 <이름>을 보내세요.')
            if project_id not in {p['id'] for p in self.projects()}:raise ValueError('선택한 프로젝트가 삭제되었거나 휴지통에 있습니다. 새 DM으로 다른 프로젝트를 선택하세요.')
            self.bind_thread(event['thread_ts'],project_id)
            with self.db() as c:c.execute('UPDATE remote_events SET project_id=? WHERE id=?',(project_id,event['id']))
            state=self.controller.state(project_id);session=state['session'];title=next(p['title'] for p in self.projects() if p['id']==project_id)
            if compact in {'중지','중지해','연구중지','연구중지해','멈춰','stop'}:
                if session:self.controller.control(dict(project_id=project_id,action='stop'))
                else:self.controller.cancel_project(project_id)
                self.finish(event,title+' · 중지를 요청했습니다. 진행 중인 작업 정리 후 저장된 결과를 보고합니다.',project_id);return
            if compact in {'일시정지','잠시멈춰','pause'}:
                if session and session['status']=='running':self.controller.control(dict(project_id=project_id,action='pause'))
                self.finish(event,title+' · 새 작업을 시작하지 않고 대기합니다.',project_id);return
            if compact in {'상태','진행상황','status'}:
                description=(session or {}).get('message','자동 연구가 시작되지 않았습니다.')
                remaining=max(0,int((session or {}).get('config',{}).get('deadline_epoch',time.time())-time.time()))
                self.finish(event,title+' · '+(session or {}).get('status','대기')+'\n'+description+f"\n남은 시간 {remaining//60}분 · 실행 중인 실험 {len(state['runs'])}개",project_id);return
            if compact in {'사용량','잔여량','usage'}:
                from quota_guard import snapshot,describe
                value=snapshot(self.quota_status()) if self.quota_status else dict(providers=[])
                self.finish(event,describe(value,(session or {}).get('config',{}).get('quota_guard')),project_id);return
            resume=re.fullmatch(r'(?:재개|이어가기|resume)\s*(\d+(?:\.\d+)?)\s*(시간|분|hours?|h|minutes?|m)\s*(.*)',lower)
            if resume:
                if not session:raise ValueError('이어갈 연구가 없습니다. 로컬 CLI에서 먼저 연구를 설정하세요.')
                seconds=float(resume[1])*(3600 if resume[2] in {'시간','h','hour','hours'} else 60)
                if not math.isfinite(seconds) or not 1<=seconds<=604800:raise ValueError('이어갈 시간은 1초–7일 범위로 지정하세요.')
                tail=resume[3].strip(' ,·');payload=dict(project_id=project_id,action='resume',session_id=session['id'],duration_seconds=int(seconds))
                amount=re.fullmatch(r'(?:사용량(?:\s*감소폭)?|감소폭|quota)\s*(\d+)\s*(?:%p|퍼센트포인트)',tail)
                if amount:payload['quota_drop_percent']=int(amount[1])
                elif re.fullmatch(r'(?:사용량\s*)?보호\s*끄기|no\s*quota',tail):payload['quota_drop_percent']=None
                elif tail:raise ValueError('재개 2시간 사용량 10%p 또는 재개 2시간 보호 끄기 형식으로 보내세요.')
                result=self.controller.control(payload)['session']
                rule=(result['config'].get('quota_guard') or {}).get('drop_percent')
                self.finish(event,title+f" · 기존 기록을 유지하고 {seconds/3600:g}시간 동안 이어갑니다.\n사용량 감소 기준: "+(str(rule)+'%p' if rule is not None else '사용 안 함'),project_id);return
            if lower.startswith(('재개','이어가기','resume')):raise ValueError('재개 2시간 사용량 10%p 또는 재개 2시간 보호 끄기 형식으로 보내세요.')
            root=self.controller.root(project_id)
            reply=self.chat.send(dict(node_id=root['id'],content=text,mode='auto',request_id=self.request_id(event['id'])),origin=dict(kind='slack_dm',event_id=event['event_id'],thread_ts=event['thread_ts'],member_id=self.notifications.credentials()['member_id']))
            with self.db() as c:c.execute("UPDATE remote_events SET state='waiting_reply',chat_id=?,updated_at=? WHERE id=?",(reply['id'],now(),event['id']))
        except (ValueError,KeyError) as error:self.finish(event,str(error),project_id if project_id in {p['id'] for p in self.projects()} else None)
        except Exception:
            with self.db() as c:c.execute("UPDATE remote_events SET state='uncertain',response=?,updated_at=? WHERE id=?",('지시 처리 완료를 확인하지 못했습니다. 자동으로 반복하지 않습니다. 상태를 확인해 주세요.',now(),event['id']))

    def tick(self):
        if not self.active():return
        with self.db() as c:row=c.execute("SELECT * FROM remote_events WHERE state='pending' ORDER BY rowid LIMIT 1").fetchone()
        if row:self.dispatch(dict(row))
        with self.db() as c:waiting=[dict(r) for r in c.execute("SELECT * FROM remote_events WHERE state='waiting_reply' ORDER BY rowid")]
        for event in waiting:
            if not self.active(event['generation']):continue
            reply=self.chat.get(event['chat_id'])
            if reply['state'] in {'completed','failed','interrupted'}:
                with self.db() as c:c.execute("UPDATE remote_events SET state='completed',response=?,updated_at=? WHERE id=?",(reply['content'],now(),event['id']))
            else:self.notifications.enqueue_remote(event['project_id'],'remote:'+event['id']+':ack','같은 프로젝트 대화에서 답변을 준비하고 있습니다.',event['thread_ts'],event['generation'])
        with self.db() as c:ready=[dict(r) for r in c.execute("SELECT * FROM remote_events WHERE state IN ('completed','uncertain') AND reply_queued=0")]
        for event in ready:
            if not self.active(event['generation']):continue
            self.notifications.enqueue_remote(event['project_id'],'remote:'+event['id']+':reply',event['response'] or '처리 상태를 확인하세요.',event['thread_ts'],event['generation'])
            with self.db() as c:c.execute('UPDATE remote_events SET reply_queued=1 WHERE id=?',(event['id'],))

    def loop(self):
        while not self.closed.wait(.5):
            try:self.tick()
            except Exception:self.error='DM 지시 처리 중 오류 · 원본 이벤트를 로컬에 보존했습니다.'
    def close_client(self):
        with self.lock:
            old=self.client;self.client=None;self.transport_generation=None
        if old:
            try:old.close()
            except Exception:pass

    def socket_loop(self):
        backoff=2
        while not self.closed.wait(1):
            generation=self.settings()['generation']
            if not self.active() or self.transport_generation!=generation:self.close_client()
            if not self.active():continue
            if self.client and self.transport_generation==generation:
                self.connection='connected' if self.client.is_connected() else 'retrying'
                backoff=2;continue
            self.connection='connecting';candidate=None
            try:
                self.close_client()
                candidate=socket_client(self.credentials()['app_token'],self.notifications.credentials()['token'])
                candidate.socket_mode_request_listeners.append(self.on_socket)
                with self.lock:self.client=candidate
                candidate.connect()
                if not self.active(generation):self.close_client();continue
                self.transport_generation=generation;self.connection='connected';self.error=None
            except Exception:
                if candidate:
                    try:candidate.close()
                    except Exception:pass
                with self.lock:
                    if self.client is candidate:self.client=None
                self.connection='retrying';self.error='Socket Mode 연결 재시도 대기 · xapp 토큰과 Slack 앱 설정을 확인하세요.'
                self.closed.wait(backoff);backoff=min(60,backoff*2)
    def close(self):
        self.closed.set();self.close_client()
        if self.thread.is_alive():self.thread.join(timeout=3)
        if self.socket_thread.is_alive():self.socket_thread.join(timeout=15)
