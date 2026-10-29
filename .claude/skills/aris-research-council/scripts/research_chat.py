"""Project research conversation, independent from the running research worker."""
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import threading
import uuid

from tree_store import now
import steering


def explicit_literature_request(context):
    """Fast path for original human paper-search imperatives, never quoted evidence."""
    if context['mode']!='auto':return False
    text=context['user_message'].strip().lower()
    if '?' in text or re.search(r'실험.*(?:돌려|실행해|시작해)|\b(?:run|execute)\b.*\bexperiments?\b',text):return False
    compact=re.sub(r'[\s.!。]+','',text)
    paper_topic=bool(re.search(r'논문|문헌|\bpapers?\b|literature',context['project_goal'],re.I))
    if paper_topic and compact in {'탐색시작해','탐색시작','탐색해','너가찾아서탐색하라고','네가찾아서탐색하라고','찾아서탐색해','직접찾아서탐색해'}:return True
    return bool(re.search(r'(논문|문헌).*(찾|검색|탐색|조사).*(해줘|해주세요|하세요|해봐|시작해|하라고|해)$',compact) or re.fullmatch(r'(?:please )?(?:find|search|explore|survey)\b.*\b(?:papers?|literature)\b[.!]*',text))


def explicit_action_request(context,intent):
    """A model-selected intent is not permission: require an original human action request."""
    if context['mode']!='auto':return False
    text=re.sub(r'```[\s\S]*?(?:```|$)','',context['user_message'])
    text='\n'.join(line for line in text.splitlines() if not line.lstrip().startswith('>'))
    for pattern in [r'"[^"\n]*"',r'“[^”]*”',r'‘[^’]*’',r'「[^」]*」',r"(?<![A-Za-z])'[^'\n]+'(?![A-Za-z])",r'`[^`\n]+`']:text=re.sub(pattern,'',text)
    lower=text.strip().lower();compact=re.sub(r'\s+','',lower)
    if not compact:return False
    if '?' in lower and not re.match(r'^(?:can you|could you|would you)\s+',lower) and not re.search(r'(?:줘|주세요|줄래|주실래)\?',compact):return False
    negatives={
        'execute':r'(?:실험|실행|돌리|연구|카운실|council).{0,24}(?:하지마|하지말|하지않고|돌리지마|돌리지말|말고)|\b(?:do not|don\x27t|never)\s+(?:run|execute|resume|start)|without.{0,20}experiment',
        'literature':r'(?:검색|탐색|조사).{0,8}(?:하지마|하지말|하지않고)|\b(?:do not|don\x27t)\s+(?:search|find)',
        'investigate':r'(?:탐색|확인|조사).{0,8}(?:하지마|하지말|하지않고)|\b(?:do not|don\x27t)\s+(?:inspect|explore)',
    }
    if intent in negatives and (re.search(negatives[intent],lower) or re.search(negatives[intent],compact)):return False
    if intent=='literature' and explicit_literature_request({**context,'user_message':text}):return True
    english={
        'execute':r'(?:run|execute|resume|restart|start)\b',
        'investigate':r'(?:inspect|investigate|explore|check)\b',
        'literature':r'(?:find|search|survey|explore)\b',
        'direction':r'(?:direction\s*:|(?:change|use|compare|preserve|apply)\b.*\b(?:next|future|direction|experiment|checkpoint|metric|goal|instead)\b)',
        'pause':r'pause\b','stop':r'(?:stop|cancel)\b',
        'report':r'(?:report\b|visualize\b|create\b.*\breport\b)',
        'publish':r'(?:publish\b|upload\b|sync\b)',
    }
    targets={'execute':r'\b(?:experiments?|research|pipeline|automatic|gpu|cpu|code|device)\b','investigate':r'\b(?:server|code|repo|repository|folder|file|script|environment|ssh|target)\b','literature':r'\b(?:papers?|literature)\b'}
    if intent in english and re.match(r'^(?:(?:please|can you|could you|would you)\s+)?'+english[intent],lower):
        return intent not in targets or bool(re.search(targets[intent],lower))
    if not re.search(r'(?:줘|주세요|해봐|하자|하세요|해|이어가|돌려|돌리라고|실행하라고|멈춰|부탁해|부탁드립니다|줄래|주실래)[.!?。]*$',compact):return False
    patterns={
        'execute':r'(?:실험|연구|자동모드|파이프라인|gpu\d*)(?:을|를|은|는|에서|로|으로)?(?:다시|계속|바로|새로|이어서|좀)*(?:돌려|돌리|실행|시작|재개|진행|계속해)|(?:실험|연구).{0,24}(?:까지이어가|까지계속해)|(?:그거|그걸|이대로)(?:다시|좀)*(?:돌려|실행)',
        'literature':r'(?:논문|문헌).*(?:찾|검색|탐색|조사)|탐색시작',
        'investigate':r'(?:서버|코드|폴더|파일|환경|ssh).*(?:탐색|확인|조사|찾|읽)',
        'direction':r'(?:바꿔|변경|반영)|(?:방향|다음실험|앞으로|설정|체크포인트|평가지표|목표).*(?:유지|비교|사용|적용|초점|전환)',
        'pause':r'(?:일시정지|잠시멈|잠깐멈)',
        'stop':r'(?:중지|멈춰|멈추|취소|그만)',
        'report':r'(?:보고서|리포트|시각화|차트|그래프).*(?:정리|요약|작성|생성|만들|그려)|(?:시각화해|보고해)',
        'publish':r'(?:노션|notion).*(?:정리|올려|업로드|저장|동기화|등록)',
    }
    return bool(intent in patterns and re.search(patterns[intent],compact))


class ResearchChat:
    def __init__(self,store,research,control,autostart=True):
        self.store,self.research,self.control=store,research,control
        self.lock=threading.RLock();self.closed=threading.Event();self.process=None;self.active_id=None;self.cancelled=set()
        with store._connect() as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS research_chat (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT NOT NULL UNIQUE,
                project_id TEXT NOT NULL,node_id TEXT NOT NULL,role TEXT NOT NULL,
                content TEXT NOT NULL,state TEXT NOT NULL,request_id TEXT NOT NULL,
                metadata TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,
                UNIQUE(project_id,request_id,role))''')
            conn.execute("UPDATE research_chat SET state='interrupted',content='앱이 종료되어 답변 작성을 멈췄습니다. 메시지를 다시 보내면 새 답변을 요청합니다.',updated_at=? WHERE state IN ('queued','running','preparing')",(now(),))
        self.thread=threading.Thread(target=self._loop,daemon=True,name='braindance-chat')
        if autostart:self.thread.start()

    @staticmethod
    def decode(row):
        row=dict(row);row['metadata']=json.loads(row['metadata']);return row

    def messages(self,project_id):
        root=self.control.root(project_id);self.store.get_node(root['id'])
        with self.store._connect() as conn:
            rows=[self.decode(r) for r in conn.execute('SELECT * FROM research_chat WHERE project_id=? ORDER BY seq DESC LIMIT 120',(project_id,))]
            for note in conn.execute("SELECT n.* FROM notes n JOIN node_projects p ON p.node_id=n.node_id WHERE p.project_id=? AND (n.kind IN ('result','analysis','publication') OR n.title LIKE '%필요한 항목%' OR n.title='실행 한도 변경') ORDER BY n.created_at DESC,n.rowid DESC LIMIT 30",(project_id,)):
                rows.append(dict(id='report:'+note['id'],project_id=project_id,node_id=note['node_id'],role='report',state='completed',title=note['title'],content=note['content'][:24000],created_at=note['created_at'],metadata=dict(note_id=note['id'])))
        jobs=self.research.list(project_id)['jobs'][:8]
        for job in jobs:
            rows.append(dict(id='job:'+job['id'],project_id=project_id,node_id=job['node_id'],role='status',state=job['state'],content=job['message'],phase=job['phase'],created_at=job['created_at'],metadata=dict(job_id=job['id'])))
        rows.sort(key=lambda r:(r['created_at'],r.get('seq',0),r['id']))
        return dict(messages=rows,project_id=project_id)

    def reply_reference(self,value,project_id):
        if value is None:return None
        if not isinstance(value,dict) or set(value)!={'type','id'}:raise ValueError('답글 대상을 확인하세요.')
        kind=value['type'];identity=value['id']
        if not isinstance(kind,str) or kind not in {'job','session','run'} or not isinstance(identity,str) or not re.fullmatch(r'[a-zA-Z0-9-]{1,100}',identity):raise ValueError('답글 대상이 올바르지 않습니다.')
        try:
            if kind=='job':
                source=self.research.get(identity);title='실험 준비 확인' if source['phase']=='blocked' else '연구 작업 확인'
                message=source.get('error') or source['message']
            elif kind=='session':
                source=self.control.get(identity);title='자동모드 확인';message=source['message']
            else:
                with self.store._connect() as conn:row=conn.execute('SELECT project_id,state,error FROM experiment_runs WHERE id=?',(identity,)).fetchone()
                if row is None:raise KeyError(identity)
                source=dict(row);title='실험 실행 확인';message=source['error'] or source['state']
        except KeyError:raise ValueError('답글 대상을 찾을 수 없습니다.')
        if source['project_id']!=project_id:raise ValueError('다른 프로젝트의 문제에는 답글을 보낼 수 없습니다.')
        return dict(type=kind,id=identity,title=title,message=message[:6000])

    def send(self,payload,*,origin=None,direct_reply=None):
        if set(payload)-{'node_id','content','mode','request_id','reply_to'} or not {'node_id','content','mode','request_id'}<=set(payload):raise ValueError('메시지·반영 방식·요청 ID를 확인하세요.')
        node=self.store.get_node(payload['node_id']);content=payload['content'];mode=payload['mode'];request_id=payload['request_id']
        if not isinstance(content,str) or not content.strip() or len(content)>6000:raise ValueError('메시지는 1–6000자로 입력하세요.')
        if mode not in {'auto','ask','next','restart'}:raise ValueError('대화 반영 방식을 확인하세요.')
        if not isinstance(request_id,str) or not re.fullmatch(r'[a-zA-Z0-9-]{16,80}',request_id):raise ValueError('요청 ID가 올바르지 않습니다.')
        reply_to=self.reply_reference(payload.get('reply_to'),node['project_id'])
        with self.lock,self.store._connect() as conn:
            old=conn.execute("SELECT * FROM research_chat WHERE project_id=? AND request_id=? AND role='assistant'",(node['project_id'],request_id)).fetchone()
            if old:
                previous=conn.execute("SELECT content FROM research_chat WHERE project_id=? AND request_id=? AND role='user'",(node['project_id'],request_id)).fetchone()
                old_meta=json.loads(old['metadata']);old_reply=old_meta.get('reply_to')
                reference=lambda item:(item['type'],item['id']) if item else None
                if old['node_id']!=node['id'] or previous['content']!=content.strip() or old_meta['mode']!=mode or reference(old_reply)!=reference(reply_to):raise ValueError('같은 요청 ID의 메시지 내용이 바뀌었습니다.')
                return self.decode(old)
            if mode=='auto' and direct_reply is None:
                from experiment_requests import parse,reply
                request=parse(content)
                if request is not None:
                    result=self.control.add_experiment(dict(project_id=node['project_id'],content=request,request_id=request_id))
                    direct_reply=dict(reply=reply(result),intent='experiment_request',experiment_request_id=result['id'])
            if direct_reply is None and conn.execute("SELECT count(*) FROM research_chat WHERE project_id=? AND state IN ('queued','running')",(node['project_id'],)).fetchone()[0]>=4:raise ValueError('답변 대기 메시지가 많습니다. 진행 중인 답변을 기다려 주세요.')
            revision=steering.snapshot(self.store,node['project_id'])['revision']
            metadata=dict(mode=mode,direction_revision_at_send=revision)
            if origin is not None:metadata['origin']=origin
            if direct_reply is not None:metadata.update(reply_model_calls=0,intent=direct_reply.get('intent','question'))
            if direct_reply is not None and direct_reply.get('experiment_request_id'):metadata['experiment_request_id']=direct_reply['experiment_request_id']
            if reply_to:metadata['reply_to']=reply_to
            timestamp=now();reply_id=str(uuid.uuid4())
            for role,text,state,msg_id in [('user',content.strip(),'completed',str(uuid.uuid4())),('assistant',direct_reply['reply'] if direct_reply is not None else '', 'completed' if direct_reply is not None else 'preparing' if mode in {'next','restart'} else 'queued',reply_id)]:
                conn.execute('INSERT INTO research_chat(id,project_id,node_id,role,content,state,request_id,metadata,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
                    (msg_id,node['project_id'],node['id'],role,text,state,request_id,json.dumps(metadata),timestamp,timestamp))
        # Explicit direction controls take effect immediately, without waiting for a reply.
        if mode in {'next','restart'}:
            try:
                result=self.control.intervene(dict(node_id=node['id'],content=content,apply_mode=mode))
                metadata['direction_applied']=result['revision']
                with self.store._connect() as conn:conn.execute("UPDATE research_chat SET metadata=?,state='queued' WHERE id=?",(json.dumps(metadata),reply_id))
            except Exception as error:
                self.finish(reply_id,'지시는 적용하지 못했습니다: '+str(error),'failed',metadata)
        return self.get(reply_id)

    def get(self,msg_id):
        with self.store._connect() as conn:row=conn.execute('SELECT * FROM research_chat WHERE id=?',(msg_id,)).fetchone()
        if row is None:raise KeyError('대화 메시지를 찾을 수 없습니다.')
        return self.decode(row)

    def finish(self,msg_id,content,state,metadata):
        with self.store._connect() as conn:conn.execute('UPDATE research_chat SET content=?,state=?,metadata=?,updated_at=? WHERE id=?',(content,state,json.dumps(metadata,ensure_ascii=False),now(),msg_id))

    def context(self,message):
        project_id=message['project_id'];root=self.control.root(project_id);selected=self.store.get_node(message['node_id'])
        state=self.control.state(project_id)
        with self.store._connect() as conn:
            history=[dict(r) for r in conn.execute("SELECT role,content FROM research_chat WHERE project_id=? AND state='completed' AND seq<? AND request_id!=? ORDER BY seq DESC LIMIT 10",(project_id,message['seq'],message['request_id']))]
            user=conn.execute("SELECT content FROM research_chat WHERE project_id=? AND request_id=? AND role='user'",(project_id,message['request_id'])).fetchone()['content']
        jobs=self.research.list(project_id)['jobs'][:3]
        runs=[]
        for run in state['runs'][:2]:
            actual=self.control.experiments.run_info(run['id']);runs.append({**run,'stdout_tail':actual['stdout_tail'][-5000:],'stderr_tail':actual['stderr_tail'][-3000:]})
        publication=None;service=getattr(self,'publications',None)
        if service:
            publication_state=service.state(project_id)
            publication=dict(connected=publication_state['connected'],auto_sync=bool((publication_state['link'] or {}).get('auto_sync')),jobs=[{k:j.get(k) for k in ['state','message','page_url','updated_at']} for j in publication_state['jobs'][:3]],chart_count=len((publication_state['report'] or {}).get('charts',[])))
        from project_session import context
        return dict(as_of=now(),shared_project_session=context(self.store,project_id),project_goal=root['metadata'].get('research_goal',root['title']),selected_node={k:selected[k] for k in ['id','title','kind','metadata','evidence']},
            actual_session=state['session'],model_usage=state.get('usage'),current_runs=runs,publication_status=publication,recent_reports=[{**n,'content':n['content'][:6000]} for n in state['reports'][:3]],
            actual_jobs=[{k:j[k] for k in ['id','state','phase','message']} for j in jobs],human_directions=state['directions'][:6],
            conversation=list(reversed(history)),user_message=user,reply_to=message['metadata'].get('reply_to'),mode=message['metadata']['mode'],direction_already_applied=message['metadata'].get('direction_applied'),
            reply_policy=dict(budget_scope='conversation_reply',independent_from_research_deadline=True,research_requires_explicit_instruction=True))

    def execute(self,message):
        root=self.research.root/('chat-'+message['id']);root.mkdir(mode=0o700,exist_ok=True)
        metadata=message['metadata'];self.finish(message['id'],'','running',metadata)
        try:
            context=self.context(message)
            context['allowed_actions']=[intent for intent in ['direction','pause','stop','investigate','execute','literature','report','publish'] if explicit_action_request(context,intent)]
            if explicit_literature_request(context) and explicit_action_request(context,'literature'):
                try:action=self.control.conversation_action(message['id'],message['node_id'],'literature',context['user_message'],metadata['direction_revision_at_send'])
                except (ValueError,RuntimeError) as error:
                    metadata['action_error']=str(error);context['research_action_unavailable']=str(error)
                else:
                    metadata.update(intent='literature',action_id=action['id'],action_kind='literature',as_of=context['as_of'],reply_model_calls=0)
                    from council import dump
                    dump(root/'chat-response.json',dict(reply='공식 논문 탐색·출처 확인 작업을 요청했습니다. 진행 기록과 탐색 결과를 같은 프로젝트 대화에 남깁니다. 실험은 실행하지 않습니다.',intent='literature',action_id=action['id']))
                    self.finish(message['id'],'공식 논문 탐색·출처 확인 작업을 요청했습니다. 진행 기록과 탐색 결과를 같은 프로젝트 대화에 남깁니다. 실험은 실행하지 않습니다.','completed',metadata)
                    return
            available=self.research.availability()
            if not available.get('chat_available',available['available']):raise ValueError('연구 대화 연결을 확인하세요: '+', '.join(available['missing']))
            session=context['actual_session']
            job=dict(id=message['id'],task='chat',db=self.store.db_path,node_id=message['node_id'],project_id=message['project_id'],
                aris_repo=available['aris_repo'],phase_timeout_seconds=240,chat_context=context)
            from project_session import identity
            job['project_session']=identity(self.store,message['project_id'])
            # Replies retain the same project thread/history, but never borrow research execution time.
            metadata['reply_budget_scope']='conversation_reply'
            from council import dump
            dump(root/'job.json',job)
            with (root/'worker.stdout.log').open('wb') as out,(root/'worker.stderr.log').open('wb') as err:
                with self.lock:
                    if self.closed.is_set() or message['id'] in self.cancelled:raise InterruptedError('대화 요청을 중지했습니다.')
                    process=subprocess.Popen(self.research.command()+[str(root/'job.json')],stdout=out,stderr=err,start_new_session=True)
                    self.process=process
                try:code=process.wait(timeout=270)
                finally:
                    if process.poll() is None:os.killpg(process.pid,signal.SIGTERM);process.wait(timeout=12)
            if self.closed.is_set():raise InterruptedError('앱이 종료되어 답변을 중지했습니다.')
            if code or not (root/'chat-response.json').is_file():
                error=(root/'progress.json')
                raise ValueError(json.loads(error.read_text()).get('message','답변을 완료하지 못했습니다.') if error.exists() else '답변을 완료하지 못했습니다.')
            result=json.loads((root/'chat-response.json').read_text());reply=result['reply'];intent=result['intent']
            if not isinstance(reply,str) or not reply.strip() or len(reply)>18000 or intent not in {'question','direction','pause','stop','investigate','execute','literature','report','publish'}:raise ValueError('대화 응답 형식이 올바르지 않습니다. 원본 로그를 보존했습니다.')
            if metadata['mode']=='auto' and intent!='question' and not explicit_action_request(context,intent):
                metadata['withheld_intent']=intent;intent='question'
                reply+='\n\n질문·정리로 처리했으며, 실험이나 Council을 포함한 추가 연구 작업은 시작하지 않았습니다.'
            if metadata['mode']=='auto' and intent!='question':
                if intent=='direction':
                    revision=steering.snapshot(self.store,message['project_id'])['revision']
                    if revision!=metadata['direction_revision_at_send']:
                        reply+='\n\n답변 작성 중 새 방향 지시가 들어와, 이 메시지의 방향 변경은 적용하지 않았습니다.'
                    else:
                        action=self.control.intervene(dict(node_id=message['node_id'],content=context['user_message'],apply_mode='next'))
                        metadata['direction_applied']=action['revision'];reply+='\n\n다음 작업에 반영할 방향 지시로 저장했습니다.'
                elif intent in {'report','publish'}:
                    service=getattr(self,'publications',None)
                    try:
                        if service is None:raise ValueError('결과 정리 서비스를 사용할 수 없습니다.')
                        receipt=service.enqueue(message['project_id'],publish=intent=='publish')
                        metadata['publication_job']=receipt['id']
                        reply+='\n\n'+('Notion 정리를 요청했습니다.' if intent=='publish' else '보고서와 시각화 생성을 요청했습니다.')+' 결과 탭과 같은 프로젝트 대화에서 완료 여부를 확인할 수 있습니다.'
                    except ValueError as error:reply+='\n\n'+str(error)
                elif intent in {'investigate','execute','literature'}:
                    try:
                        if intent=='literature' and context.get('research_action_unavailable'):raise ValueError(context['research_action_unavailable'])
                        action=self.control.conversation_action(message['id'],message['node_id'],intent,context['user_message'],metadata['direction_revision_at_send'])
                        metadata['action_id']=action['id'];metadata['action_kind']=intent
                        reply+='\n\n'+('공식 논문 탐색·출처 확인 작업을 요청했습니다. 결과는 같은 프로젝트 대화에 저장하며 실험은 실행하지 않습니다.' if intent=='literature' else '서버·코드의 읽기 전용 탐색을 요청했습니다. 결과는 이 프로젝트 대화에 이어집니다.' if intent=='investigate' else '기존 프로젝트 세션을 재개했습니다. 같은 대화와 연구 기록을 바탕으로 탐색 → 코드 검토 → 선택한 장치·남은 예산 내 실행 → 결과 분석을 이어갑니다.')
                    except (ValueError,RuntimeError) as error:
                        reply+='\n\n작업은 시작하지 않았습니다: '+str(error);metadata['action_error']=str(error)
                else:
                    if session:
                        self.control.control(dict(project_id=message['project_id'],action=intent));metadata['control_applied']=intent
                    elif intent=='stop':
                        self.control.cancel_project(message['project_id']);metadata['control_applied']=intent
                    else:reply+='\n\n현재 일시정지할 자동모드 실행은 없습니다.'
                    if metadata.get('control_applied'):reply+='\n\n'+('프로젝트 작업을 중지했습니다.' if intent=='stop' else '자동모드를 일시정지했습니다.')
            metadata.update(intent=intent,as_of=context['as_of'],receipt=str(root/'chat-response.json'))
            usage=root/'chat-usage.json'
            if usage.is_file():metadata['reported_tokens']=json.loads(usage.read_text()).get('observed_tokens')
            if metadata.get('direction_applied'):reply+='\n\n지시 반영 기록: '+str(metadata['direction_applied'])
            self.finish(message['id'],reply.strip(),'completed',metadata)
        except Exception as error:
            import traceback
            (root/'chat-error.log').write_text(traceback.format_exc())
            self.finish(message['id'],'답변을 완료하지 못했습니다: '+str(error),'interrupted' if self.closed.is_set() or message['id'] in self.cancelled else 'failed',metadata)
        finally:
            with self.lock:self.process=None

    def _loop(self):
        while not self.closed.wait(.3):
            with self.lock:
                with self.store._connect() as conn:row=conn.execute("SELECT * FROM research_chat WHERE role='assistant' AND state='queued' ORDER BY seq LIMIT 1").fetchone()
                if row is None:continue
                message=self.decode(row);self.active_id=message['id']
            self.execute(message)
            with self.lock:self.active_id=None

    def cancel_project(self,project_id):
        with self.lock,self.store._connect() as conn:
            conn.execute("UPDATE research_chat SET state='interrupted',content='프로젝트가 종료되어 답변 요청을 중지했습니다.',updated_at=? WHERE project_id=? AND state IN ('queued','preparing')",(now(),project_id))
            if self.active_id:
                active=conn.execute('SELECT project_id FROM research_chat WHERE id=?',(self.active_id,)).fetchone()
                if active and active['project_id']==project_id:
                    self.cancelled.add(self.active_id)
                    if self.process and self.process.poll() is None:
                        try:os.killpg(self.process.pid,signal.SIGTERM)
                        except ProcessLookupError:pass

    def close(self):
        self.closed.set()
        with self.lock:
            if self.process and self.process.poll() is None:
                try:os.killpg(self.process.pid,signal.SIGTERM)
                except ProcessLookupError:pass
        if self.thread.is_alive():self.thread.join(timeout=15)
