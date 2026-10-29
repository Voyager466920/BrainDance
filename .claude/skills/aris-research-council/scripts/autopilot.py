"""Project-scoped, human-steerable research sessions with durable stage receipts."""
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time
import traceback
import uuid

from experiments import resource_signature,TERMINAL
from tree_store import now
import steering


class Autopilot:
    def __init__(self,store,research,experiments,autostart=True,quota_status=None):
        self.store,self.research,self.experiments=store,research,experiments
        self.lock=threading.RLock();self.closed=threading.Event()
        self.default_pipeline='aris-native'
        self.sleep_guard=None;self.quota_status=quota_status;self.quota_next={}
        steering.initialize(store)
        with store._connect() as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS conversation_actions (
                id TEXT PRIMARY KEY,project_id TEXT NOT NULL,node_id TEXT NOT NULL,kind TEXT NOT NULL,
                state TEXT NOT NULL,content TEXT NOT NULL,job_id TEXT,receipt TEXT NOT NULL,created_at TEXT NOT NULL)''')
            conn.execute("UPDATE conversation_actions SET state='interrupted' WHERE state IN ('pending','running','applying')")
            conn.execute('''CREATE TABLE IF NOT EXISTS automatic_sessions (
                id TEXT PRIMARY KEY,project_id TEXT NOT NULL,node_id TEXT NOT NULL,
                status TEXT NOT NULL,message TEXT NOT NULL,config TEXT NOT NULL,
                progress TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL)''')
            for row in conn.execute("SELECT id,config FROM automatic_sessions WHERE status='running'").fetchall():
                if json.loads(row['config']).get('execution_policy')!='until_deadline':conn.execute("UPDATE automatic_sessions SET status='paused',message='앱을 다시 열었습니다. 자동모드 재개를 누르면 남은 한도에서 이어갑니다.' WHERE id=?",(row['id'],))
        experiments.plan_guard=self.guard
        self.thread=threading.Thread(target=self._loop,daemon=True,name='braindance-automatic')
        if autostart:self.thread.start()

    @staticmethod
    def decode(row):
        item=dict(row)
        for key in ['config','progress']:item[key]=json.loads(item[key])
        return item

    def sessions(self,project_id):
        with self.store._connect() as conn:return [self.decode(r) for r in conn.execute('SELECT * FROM automatic_sessions WHERE project_id=? ORDER BY rowid DESC',(project_id,))]

    def get(self,session_id):
        with self.store._connect() as conn:row=conn.execute('SELECT * FROM automatic_sessions WHERE id=?',(session_id,)).fetchone()
        if row is None:raise KeyError('자동모드 실행을 찾을 수 없습니다.')
        return self.decode(row)

    def root(self,project_id):
        root=next((n for n in self.store.export_json()['nodes'] if n['project_id']==project_id and not n['parent_id']),None)
        if root is None:raise KeyError('프로젝트를 찾을 수 없습니다.')
        return root

    def state(self,project_id):
        root=self.root(project_id);self.store.get_node(root['id'])
        sessions=self.sessions(project_id);current=sessions[0] if sessions else None
        with self.store._connect() as conn:
            directions=[dict(r) for r in conn.execute('SELECT * FROM research_directions WHERE project_id=? ORDER BY seq DESC LIMIT 20',(project_id,))]
            runs=[dict(r) for r in conn.execute("SELECT r.id,r.state,r.experiment_id,e.node_id,e.spec FROM experiment_runs r JOIN experiments e ON e.id=r.experiment_id WHERE r.project_id=? AND r.state IN ('queued','running') ORDER BY r.queued_at",(project_id,))]
            reports=[dict(r) for r in conn.execute("SELECT n.* FROM notes n JOIN node_projects p ON p.node_id=n.node_id WHERE p.project_id=? AND n.kind IN ('result','analysis') ORDER BY n.created_at DESC,n.rowid DESC LIMIT 8",(project_id,))]
        for run in runs:
            spec=json.loads(run.pop('spec'));run.update(title=spec['title'],device_ids=spec['device_ids'],timeout_seconds=spec['timeout_seconds'])
        usage=None
        if current:
            path=Path(current['config']['session_budget'])
            if path.is_file():
                raw=json.loads(path.read_text());usage=dict(calls=raw['calls'],max_calls=raw['max_calls'],charged_tokens=sum(raw['charges'].values()),observed_tokens=sum(raw.get('observed',{}).values()),token_budget=raw['token_budget'],policy=raw.get('policy','bounded'),deadline_epoch=raw.get('deadline_epoch'),anthropic_usage={key:sum(v.get(key,0) for v in raw.get('anthropic_usage',{}).values()) for key in ['input_tokens','output_tokens','cache_read_input_tokens','cache_creation_input_tokens']})
        from research_tasks import listing
        return dict(session=current,directions=directions,runs=runs,reports=reports,usage=usage,tasks=listing(self.store,current['id']) if current else [])

    def save(self,item,status=None,message=None,**progress):
        item['progress'].update(progress)
        if status:item['status']=status
        if message:item['message']=message
        with self.store._connect() as conn:
            conn.execute('UPDATE automatic_sessions SET status=?,message=?,progress=?,updated_at=? WHERE id=?',
                (item['status'],item['message'],json.dumps(item['progress']),now(),item['id']))

    def control(self,payload):
        if set(payload)-{'project_id','action','max_cycles','max_model_calls','token_budget','context_path','mode','session_id','reuse_research','research_style','execution_policy','duration_seconds','deadline_epoch','experiment_timeout_seconds','orchestration','cost_profile','quota_drop_percent'}:raise ValueError('지원하지 않는 자동모드 설정입니다.')
        project_id=payload['project_id'];action=payload['action'];root=self.root(project_id);self.store.get_node(root['id'])
        if 'experiment_timeout_seconds' in payload:
            value=payload['experiment_timeout_seconds']
            if value is not None and (type(value) is not int or not 1<=value<=86400):raise ValueError('실험당 제한 시간은 1초–24시간 또는 자동 배분으로 설정하세요.')
        if payload.get('orchestration','single') not in {'single','hypothesis-tasks'}:raise ValueError('연구 작업 구성을 확인하세요.')
        if payload.get('cost_profile','standard') not in {'economy','standard'}:raise ValueError('절약 또는 표준 사용량 설정을 선택하세요.')
        if action not in {'start','pause','resume','stop','limits','time_only','deadline','portfolio','cost_profile'}:raise ValueError('자동모드 동작을 확인하세요.')
        with self.lock:
            old=self.sessions(project_id);item=old[0] if old else None
            if action=='resume' and 'quota_drop_percent' in payload and not {'duration_seconds','deadline_epoch'}&set(payload):raise ValueError('사용량 기준을 바꾸려면 이어갈 시간도 지정하세요.')
            if action=='resume' and payload.get('session_id') and (not item or payload['session_id']!=item['id']):raise ValueError('연구 세션이 바뀌었습니다. 이어가기 설정을 다시 여세요.')
            if action=='resume' and ('duration_seconds' in payload or 'deadline_epoch' in payload):
                if not item:raise ValueError('이어갈 연구가 없습니다.')
                from research_continue import continue_session
                return continue_session(self,item,payload)
            if action=='cost_profile':
                if not item:raise ValueError('자동 연구 세션을 먼저 선택하세요.')
                profile=payload.get('cost_profile')
                if profile not in {'economy','standard'}:raise ValueError('절약 또는 표준 사용량 설정을 선택하세요.')
                item['config']['cost_profile']=profile
                with self.store._connect() as conn:conn.execute('UPDATE automatic_sessions SET config=? WHERE id=?',(json.dumps(item['config']),item['id']))
                return self.state(project_id)
            if action=='portfolio':
                if not item:raise ValueError('먼저 시간 제한 자율 연구를 시작하세요.')
                if item['config'].get('execution_policy')!='until_deadline':raise ValueError('시간 제한 자율 연구에서 가설별 작업을 사용하세요.')
                item['config']['orchestration']='hypothesis-tasks'
                with self.store._connect() as conn:conn.execute('UPDATE automatic_sessions SET config=? WHERE id=?',(json.dumps(item['config']),item['id']))
                self.save(item,message='넓은 탐색 후 가설별 공식 연구 작업으로 분리합니다.',phase='prepare',job_id=None)
                return self.state(project_id)
            if action in {'time_only','deadline'}:
                if not item:raise ValueError('먼저 프로젝트 자동모드를 시작하세요.')
                if action=='deadline' and item['config'].get('execution_policy')!='until_deadline':raise ValueError('먼저 시간 제한 모드로 전환하세요.')
                _,assignment=self.experiments._resources(root)
                clock=self.deadline_spec(payload,assignment['time_budget_minutes']*60)
                if item['config'].get('started_epoch'):clock['started_epoch']=item['config']['started_epoch']
                from session_budget import update
                update(item['config']['session_budget'],'time_only',deadline_epoch=clock['deadline_epoch'],started_epoch=clock['started_epoch'])
                item['config'].update(clock,max_cycles=None,pipeline='aris-native')
                if 'experiment_timeout_seconds' in payload:item['config']['experiment_timeout_seconds']=payload['experiment_timeout_seconds']
                with self.store._connect() as conn:conn.execute('UPDATE automatic_sessions SET config=? WHERE id=?',(json.dumps(item['config']),item['id']))
                if action=='time_only':
                    p=item['progress'];current=self.research.get(p['job_id']) if p.get('job_id') else None
                    if not current or current['state'] not in {'queued','running'}:p.update(phase='prepare',job_id=None,recovery_after=0,native_cycle=p.get('native_cycle',0)+1)
                    self.save(item,'running','호출·토큰·실험 횟수 제한 없이 종료 시각까지 자율 연구를 이어갑니다.')
                self.store.add_note(root['id'],'analysis','시간 제한 자율 연구 설정',json.dumps(dict(deadline_epoch=clock['deadline_epoch'],model_calls='unlimited',tokens='unlimited',experiments='unlimited',usage_preserved=True),ensure_ascii=False))
                return self.state(project_id)
            if action=='limits':
                if set(payload)!={'project_id','action','session_id','max_model_calls','token_budget'}:raise ValueError('변경할 실행과 호출·토큰 한도를 확인하세요.')
                if not item or item['id']!=payload['session_id']:raise ValueError('자동 실행 세션이 바뀌었습니다. 한도 창을 다시 여세요.')
                from session_budget import update
                data=update(item['config']['session_budget'],'limits',max_calls=payload['max_model_calls'],token_budget=payload['token_budget'])
                with self.store._connect() as conn:
                    conn.execute('UPDATE automatic_sessions SET updated_at=? WHERE id=?',(now(),item['id']))
                    self.store._event(conn,root['id'],'automatic_limits_changed',dict(session_id=item['id'],change=data['limit_changes'][-1]))
                self.store.add_note(root['id'],'memo','실행 한도 변경',json.dumps(dict(session_id=item['id'],calls_used=data['calls'],max_calls=data['max_calls'],token_budget=data['token_budget']),ensure_ascii=False))
                return self.state(project_id)
            if action=='start':
                if item and item['status'] in {'running','paused'}:raise ValueError('기존 자동모드를 재개하거나 중지하세요.')
                from scout import settings
                preferences=settings(self.store,project_id);style=payload.get('research_style',preferences['style'])
                if style not in {'focused','scout'}:raise ValueError('연구 방식을 확인하세요.')
                if style=='scout' and not preferences['interests']:raise ValueError('탐색 모드에는 프로젝트 관심 분야가 필요합니다.')
                policy=payload.get('execution_policy','bounded')
                if policy not in {'bounded','until_deadline'}:raise ValueError('실행 정책을 확인하세요.')
                cycles=payload.get('max_cycles',preferences['max_pilots'] if style=='scout' else 3);calls=payload.get('max_model_calls',40);tokens=payload.get('token_budget',1500000)
                from session_budget import MAX_TOKEN_BUDGET,MAX_MODEL_CALLS
                for name,value,low,high in [('실험 횟수',cycles,1,30),('모델 호출 한도',calls,2,MAX_MODEL_CALLS),('토큰 한도',tokens,100000,MAX_TOKEN_BUDGET)]:
                    if policy=='bounded' and (type(value) is not int or not low<=value<=high):raise ValueError(name+'는 '+format(low,',')+'–'+format(high,',')+' 범위로 입력하세요. 입력값: '+str(value))
                context=payload.get('context_path','');mode=payload.get('mode','balanced')
                if not isinstance(context,str) or len(context)>2048 or '\x00' in context or '\n' in context or mode not in {'lite','balanced','deep'}:raise ValueError('참고 폴더·연구 모드를 확인하세요.')
                reuse=payload.get('reuse_research',False)
                if type(reuse) is not bool:raise ValueError('연구 재사용 설정은 true 또는 false여야 합니다.')
                if style=='scout' and policy=='bounded':cycles=min(cycles,preferences['max_pilots'])
                if policy=='until_deadline':cycles=calls=tokens=None
                previous=None
                if reuse:
                    for candidate in self.research.list(project_id)['jobs']:
                        folder=Path(candidate['run_dir'])
                        status=folder/'council/status.json';evidence=folder/'literature/verified-evidence.json';receipt=folder/'literature-usage.json'
                        if candidate['config'].get('task')=='research' and status.is_file() and evidence.is_file() and receipt.is_file() and json.loads(status.read_text()).get('status')=='completed' and json.loads(receipt.read_text()).get('skill_invoked'):
                            previous=candidate;break
                    if not previous or not self.has_hypotheses(project_id):raise ValueError('재사용할 완료된 Council·검증된 논문 근거와 활성 가설이 없습니다.')
                quota=None
                if payload.get('quota_drop_percent') is not None:
                    from quota_guard import capture
                    if self.quota_status is None:raise ValueError('계정 사용량 연결을 확인하세요.')
                    quota=capture(self.quota_status(force=True),payload['quota_drop_percent'])
                profile,assignment=self.experiments._resources(root)
                sid=str(uuid.uuid4());path=self.research.root/('automatic-'+sid);path.mkdir(mode=0o700)
                from project_session import identity
                native_workspace=Path(identity(self.store,project_id)['path'])/'native'
                ledger=path/'session-budget.json';ledger.write_text(json.dumps(dict(calls=0,max_calls=calls,token_budget=tokens,charges={})))
                item=dict(id=sid,project_id=project_id,node_id=root['id'],status='running',message='자동 연구를 시작합니다.',
                    config=dict(scope='project',pipeline=self.default_pipeline,research_style=style,scout_preferences=preferences,max_cycles=cycles,mode=mode,context_path=context,resource_signature=resource_signature(profile,assignment),reuse_research=reuse,
                                session_budget=str(ledger),native_workspace=str(native_workspace)),progress=dict(phase='prepare',discovery_completed=False,cycles=0,revision=steering.snapshot(self.store,project_id)['revision'],code_hashes=[],failures=0),created_at=now(),updated_at=now())
                item['config']['execution_policy']=policy
                item['config']['orchestration']=payload.get('orchestration','single')
                item['config']['cost_profile']=payload.get('cost_profile','standard')
                if quota:item['config']['quota_guard']=quota
                item['config']['experiment_timeout_seconds']=payload.get('experiment_timeout_seconds')
                if policy=='until_deadline':
                    clock=self.deadline_spec(payload,assignment['time_budget_minutes']*60);item['config'].update(clock,pipeline='aris-native')
                    from session_budget import update
                    update(ledger,'time_only',deadline_epoch=clock['deadline_epoch'],started_epoch=clock['started_epoch'])
                if previous:item['progress'].update(discovery_completed=True,research_job_id=previous['id'])
                with self.store._connect() as conn:
                    conn.execute('INSERT INTO automatic_sessions VALUES(?,?,?,?,?,?,?,?,?)',tuple(json.dumps(v) if k in {'config','progress'} else v for k,v in item.items()))
                    self.store._event(conn,root['id'],'automatic_authorized',dict(session_id=sid,limits=item['config'],scope='reviewed LLM-generated code on the selected project resources'))
                self.store.add_note(root['id'],'memo','자동모드 시작','설정한 장치·시간·모델 한도 내에서 검토된 LLM 실험을 매번 승인하지 않고 실행합니다. 세션: '+sid)
                if previous:self.store.add_note(root['id'],'memo','완료된 연구 재사용','논문·Council 결과를 재사용하고 현재 지시·장치로 실행 코드를 다시 작성·검토합니다. 이전 사용량과 실행 기록은 보존됩니다. 연구: '+previous['id'])
            elif not item:raise ValueError('자동모드를 먼저 시작하세요.')
            elif action=='pause':self.save(item,'paused','현재 작업 뒤 대기합니다. 새 실험은 시작하지 않습니다.')
            elif action=='stop':
                self.save(item,'stopped','자동모드를 중지했습니다.');self.cancel_project(project_id)
            else:
                if item['status'] not in {'paused','blocked'}:raise ValueError('중지·종료된 연구는 이어가기에서 새 시간과 사용량 기준을 설정하세요.')
                p=item['progress']
                if self.default_pipeline=='aris-native' and item['config'].get('pipeline')!='aris-native':
                    if self.busy(project_id):raise ValueError('실행 중인 실험이 끝난 뒤 새 자율 흐름으로 재개하세요.')
                    with self.store._connect() as conn:
                        if conn.execute("SELECT 1 FROM research_jobs WHERE project_id=? AND state IN ('queued','running')",(project_id,)).fetchone():raise ValueError('진행 중인 연구 작업이 끝난 뒤 재개하세요.')
                    from project_session import identity
                    item['config'].update(previous_pipeline=item['config'].get('pipeline'),legacy_progress=dict(p),pipeline='aris-native',native_workspace=str(Path(identity(self.store,project_id)['path'])/'native'))
                    with self.store._connect() as conn:
                        conn.execute('UPDATE automatic_sessions SET config=? WHERE id=?',(json.dumps(item['config']),item['id']))
                        self.store._event(conn,root['id'],'native_pipeline_resumed',dict(session_id=item['id'],previous_pipeline=item['config']['previous_pipeline'],usage_preserved=True))
                    self.store.add_note(root['id'],'memo','자율 연구 흐름 전환','기존 결과·대화·사용량·장치·예산을 보존하고 공식 자율 파이프라인으로 재개합니다. 이전 진행 기록도 세션 설정에 보존했습니다.')
                keep_tasks=item['config'].get('orchestration')=='hypothesis-tasks' and p.get('phase')=='tasks'
                if item['config'].get('pipeline')=='aris-native' and not keep_tasks:
                    current=self.research.get(p['job_id']) if p.get('job_id') else None
                    if current and current['state'] in {'queued','running'}:p['phase']='native'
                    else:p.update(phase='prepare',job_id=None)
                if p.get('job_id'):
                    prior=self.research.get(p['job_id'])
                    if self.research.can_retry(prior):self.research.retry(prior['id']);p.update(phase='job',run_id=None)
                # A resume is explicit permission to prepare a replacement for an interrupted/blocked job.
                if p.get('job_id') and self.research.get(p['job_id'])['state'] in {'interrupted','cancelled','failed'}:p.update(phase='prepare',job_id=None)
                if p.get('run_id') and self.experiments.run_info(p['run_id'])['state'] in {'interrupted','blocked','cancelled'}:p.update(phase='prepare',run_id=None)
                if item['status']=='blocked' and p.get('job_id'):
                    prior=self.research.get(p['job_id'])
                    reusable=prior['state'] in {'queued','running'} or (prior['state']=='completed' and prior['phase'] in {'experiment_approval','analyzed'})
                    if not reusable:p.update(phase='prepare',job_id=None,run_id=None)
                self.save(item,'running','남은 예산에서 자동모드를 재개합니다.')
            return self.state(project_id)

    @staticmethod
    def deadline_spec(payload,default_seconds):
        duration=payload.get('duration_seconds',default_seconds)
        if type(duration) is not int or not 1<=duration<=604800:raise ValueError('연구 시간은 1초–7일 범위로 지정하세요.')
        end=payload.get('deadline_epoch',time.time()+duration)
        if isinstance(end,bool) or not isinstance(end,(int,float)) or not math.isfinite(end) or not time.time()<end<=time.time()+604800:raise ValueError('종료 시각은 지금부터 7일 안으로 지정하세요.')
        return dict(execution_policy='until_deadline',started_epoch=end-duration,deadline_epoch=end,duration_seconds=duration)

    def expire(self,item):
        self.save(item,'completed','연구 시간이 끝나 연구·실험을 중지했습니다. 질문과 결과 정리는 대화에서 계속할 수 있습니다.',phase='deadline')
        self.cancel_project(item['project_id'])
        callback=getattr(self,'deadline_callback',None)
        if callback:callback(item['project_id'])
        self.store.add_note(item['node_id'],'analysis','시간 제한 종료 보고',json.dumps(dict(deadline_epoch=item['config']['deadline_epoch'],completed_cycles=item['progress'].get('cycles_completed',0),usage=self.state(item['project_id'])['usage'],message='종료 시각 이후 새 연구 호출과 실험을 시작하지 않습니다. 원본 로그와 실제 결과를 보존하며, 질문과 결과 정리는 계속 답변합니다.'),ensure_ascii=False))

    def cancel_project(self,project_id):
        from research_tasks import initialize
        initialize(self.store)
        with self.store._connect() as conn:conn.execute("UPDATE research_tasks SET state='stopped',message='프로젝트 중지 또는 종료 시각 도달' WHERE project_id=? AND state IN ('queued','running')",(project_id,))
        for job in self.research.list(project_id)['jobs']:
            if job['state'] in {'queued','running'}:self.research.stop(job['id'])
        with self.store._connect() as conn:ids=[r['id'] for r in conn.execute("SELECT id FROM experiment_runs WHERE project_id=? AND state IN ('queued','running')",(project_id,))]
        for run_id in ids:self.experiments.cancel(run_id)

    def intervene(self,payload):
        if set(payload)!={'node_id','content','apply_mode'}:raise ValueError('노드·지시·반영 시점이 필요합니다.')
        with self.lock:
            result=steering.record(self.store,**payload)
            for item in self.sessions(result['project_id'])[:1]:
                if item['status'] in {'running','paused','blocked'}:
                    changes=dict(preferred_node=result['node_id'])
                    if self.store.get_node(result['node_id'])['kind']=='problem':changes['discovery_completed']=False
                    self.save(item,**changes)
            if payload['apply_mode']=='restart':
                self.cancel_project(result['project_id'])
                for item in self.sessions(result['project_id'])[:1]:
                    if item['status'] in {'running','paused','blocked'}:
                        self.save(item,'running','현재 작업을 중지하고 새 방향으로 준비합니다.',phase='prepare',job_id=None,run_id=None,preferred_node=result['node_id'])
            return result

    def conversation_action(self,message_id,node_id,kind,content,expected_revision):
        """Host-owned action admission, retaining existing execution authority/limits."""
        if kind not in {'investigate','execute','literature'}:raise ValueError('지원하지 않는 대화 작업입니다.')
        with self.lock:
            node=self.store.get_node(node_id);project_id=node['project_id']
            with self.store._connect() as conn:
                old=conn.execute('SELECT * FROM conversation_actions WHERE id=?',(message_id,)).fetchone()
                if old:return dict(old)
            if steering.snapshot(self.store,project_id)['revision']!=expected_revision:raise ValueError('답변 중 새 지시가 들어왔습니다. 이전 지시로 실행하지 않았습니다.')
            sessions=self.sessions(project_id);item=sessions[0] if sessions else None
            if item and item['config'].get('execution_policy')=='until_deadline' and time.time()>=item['config']['deadline_epoch']:raise ValueError('프로젝트 종료 시각에 도달했습니다. 새 종료 시각을 지정하세요.')
            if kind=='execute':
                if not item or item['status'] not in {'running','paused','blocked'}:raise ValueError('이 프로젝트의 자동모드를 먼저 설정하세요. 대화로 실행 권한이나 예산을 새로 만들지 않습니다.')
                profile,assignment=self.experiments._resources(self.root(project_id))
                if resource_signature(profile,assignment)!=item['config']['resource_signature']:raise ValueError('선택 장치·예산이 바뀌어 기존 세션으로 실행할 수 없습니다. 자동모드 설정을 확인하세요.')
                with self.store._connect() as conn:budget=self.experiments._budget(project_id,assignment['updated_at'],assignment['time_budget_minutes']*60,conn)
                if budget['remaining_seconds']<1 or item['config']['max_cycles'] is not None and item['progress']['cycles']>=item['config']['max_cycles']:raise ValueError('설정된 실행 시간 또는 실험 횟수를 소진했습니다.')
                from session_budget import update
                update(item['config']['session_budget'],'check')
            with self.store._connect() as conn:conn.execute('INSERT INTO conversation_actions VALUES(?,?,?,?,?,?,?,?,?)',(message_id,project_id,node_id,kind,'applying' if kind=='execute' else 'pending',content,None,'{}',now()))
            try:
                if kind=='execute':
                    discovered=item['progress'].get('discovery_completed',False)
                    result=self.intervene(dict(node_id=node_id,content=content,apply_mode='next'))
                    active=self.research.active_id is not None or self.busy(project_id)
                    progress=dict(discovery_completed=discovered,preferred_node=node_id)
                    if not active and not (item['config'].get('orchestration')=='hypothesis-tasks' and item['progress'].get('phase')=='tasks'):progress.update(phase='prepare',job_id=None,run_id=None,failures=0)
                    self.save(item,'running','대화 지시로 기존 서버·코드를 탐색하고 남은 한도에서 실험을 이어갑니다.',**progress)
                    receipt=dict(session_id=item['id'],direction_revision=result['revision'],status='running',limits_unchanged=True)
                    state='applied'
                else:receipt=dict(status='queued',read_only=True);state='pending'
                with self.store._connect() as conn:conn.execute('UPDATE conversation_actions SET state=?,receipt=? WHERE id=?',(state,json.dumps(receipt),message_id))
            except Exception as error:
                with self.store._connect() as conn:conn.execute("UPDATE conversation_actions SET state='blocked',receipt=? WHERE id=?",(json.dumps(dict(error=str(error))),message_id))
                raise
            with self.store._connect() as conn:return dict(conn.execute('SELECT * FROM conversation_actions WHERE id=?',(message_id,)).fetchone())

    def _conversation_requests(self):
        with self.store._connect() as conn:items=[dict(r) for r in conn.execute("SELECT * FROM conversation_actions WHERE kind IN ('investigate','literature') AND state IN ('pending','running') ORDER BY created_at")]
        for action in items:
            try:
                self.store.get_node(action['node_id'])
                if action['state']=='running':
                    job=self.research.get(action['job_id'])
                    if job['state'] in {'running','queued'}:continue
                    with self.store._connect() as conn:conn.execute('UPDATE conversation_actions SET state=?,receipt=? WHERE id=?',('completed' if job['state']=='completed' else 'blocked',json.dumps(dict(job_id=job['id'],message=job['message'])),action['id']))
                    continue
                if self.research.active_id is not None or self.busy(action['project_id']):continue
                sessions=self.sessions(action['project_id']);item=sessions[0] if sessions else None
                previous=self.research.list(action['project_id'])['jobs']
                context=item['config']['context_path'] if item else next((j['config']['context_path'] for j in previous if j['config'].get('context_path')),'')
                internal=dict(cost_profile=item['config'].get('cost_profile','standard'),auto_session_id=item['id'],session_budget=item['config']['session_budget']) if item and (item['status'] in {'running','paused','blocked'} or item['config'].get('execution_policy')=='until_deadline') else {}
                if internal:
                    from session_budget import update
                    update(internal['session_budget'],'check')
                internal['conversation_request']=dict(id=action['id'],content=action['content'])
                job=self.research.start(dict(node_id=action['node_id'],task='literature' if action['kind']=='literature' else 'inspect',confirm=True,context_path=context),internal=internal)
                with self.store._connect() as conn:conn.execute("UPDATE conversation_actions SET state='running',job_id=? WHERE id=?",(job['id'],action['id']))
            except Exception as error:
                with self.store._connect() as conn:conn.execute("UPDATE conversation_actions SET state='blocked',receipt=? WHERE id=?",(json.dumps(dict(error=str(error))),action['id']))
                try:self.store.add_note(action['node_id'],'analysis','대화 작업 · 확인 필요',str(error))
                except (KeyError,ValueError):pass

    def guard(self,experiment):
        spec=experiment['spec'];generation=spec.get('generation',{})
        if 'direction_revision' in generation and generation['direction_revision']!=steering.snapshot(self.store,spec['project_id'])['revision']:
            raise ValueError('방향 지시가 바뀌었습니다. 새 지시로 실험을 다시 준비하세요.')
        sid=generation.get('auto_session_id')
        if sid:
            item=self.get(sid)
            if item['status']!='running':raise ValueError('자동모드가 실행 중이 아닙니다.')
            # Experiment admission can run inside a SQLite write transaction.
            # The controller monitors quotas and owns cancellation; this path only reads the stop flag.
            from session_budget import update
            update(item['config']['session_budget'],'check')
            if item['config']['resource_signature']!=spec['resource_signature']:raise ValueError('자동모드의 실행 환경이 바뀌었습니다.')

    def has_hypotheses(self,project_id):
        return any(n['project_id']==project_id and n['kind']=='hypothesis' and n['status']=='active' for n in self.store.export_json()['nodes'])

    def busy(self,project_id):
        with self.store._connect() as conn:return bool(conn.execute("SELECT 1 FROM experiment_runs WHERE project_id=? AND state IN ('queued','running')",(project_id,)).fetchone())

    def launch(self,item,task,node_id=None,run_id=None):
        _,assignment=self.experiments._resources(self.store.get_node(item['node_id']))
        with self.store._connect() as conn:budget=self.experiments._budget(item['project_id'],assignment['updated_at'],assignment['time_budget_minutes']*60,conn)
        return self.research.start(dict(node_id=node_id or item['node_id'],task=task,run_id=run_id,confirm=True,
            mode=item['config']['mode'],context_path=item['config']['context_path'],reuse_literature=task!='research'),
            internal=dict(cost_profile=item['config'].get('cost_profile','standard'),auto_session_id=item['id'],session_budget=item['config']['session_budget'],remaining_experiment_seconds=int(budget['remaining_seconds'])))

    def check_quota(self,item,force=False):
        guard=item['config'].get('quota_guard')
        if not guard:return True
        if not force and self.quota_next.get(item['id'],0)>time.monotonic():return True
        from quota_guard import snapshot,evaluate,describe
        try:current=snapshot(self.quota_status()) if self.quota_status else dict(providers=[])
        except Exception:current=dict(providers=[])
        self.quota_next[item['id']]=time.monotonic()+60
        decision=evaluate(guard,current)
        item['progress']['account_usage']=current
        if decision['stop']:
            from session_budget import update
            update(item['config']['session_budget'],'quota_stop',**decision)
            self.save(item,'stopped',decision['reason'],phase='quota-stop',quota_stop=decision)
            self.cancel_project(item['project_id'])
            self.store.add_note(item['node_id'],'analysis','사용량 보호 중지 · 결과 정리',decision['reason']+'\n\n'+describe(current,guard))
            return False
        with self.store._connect() as conn:conn.execute("UPDATE automatic_sessions SET progress=json_set(progress,'$.account_usage',json(?)) WHERE id=?",(json.dumps(current),item['id']))
        return True

    def tick(self,item):
        if item['status']!='running':return
        if item['config'].get('execution_policy')=='until_deadline' and time.time()>=item['config']['deadline_epoch']:self.expire(item);return
        if not self.check_quota(item):return
        node=self.store.get_node(item['node_id'])
        if node['status'] not in {'active','expanded'}:raise ValueError('프로젝트가 보류 또는 폐기되었습니다.')
        profile,assignment=self.experiments._resources(node)
        if resource_signature(profile,assignment)!=item['config']['resource_signature']:raise ValueError('실행 환경·장치·예산이 변경되어 자동모드를 멈췄습니다.')
        if item['config'].get('pipeline')=='aris-native':
            return self.native_tick(item)
        p=item['progress'];phase=p['phase'];revision=steering.snapshot(self.store,item['project_id'])['revision']
        if phase=='prepare':
            if self.research.active_id is not None or self.busy(item['project_id']):return
            if p['cycles']>=item['config']['max_cycles']:
                self.save(item,'completed','설정한 실험 횟수를 완료했습니다.');return
            if p['failures']>=2:raise ValueError('연속 두 번의 실패 후 자동모드를 멈췄습니다. 보고와 방향을 확인하세요.')
            with self.store._connect() as conn:
                budget=self.experiments._budget(item['project_id'],assignment['updated_at'],assignment['time_budget_minutes']*60,conn)
            if budget['remaining_seconds']<1:self.save(item,'completed','프로젝트 실행 시간 예산을 소진했습니다.');return
            task='draft' if p.get('discovery_completed') else 'research'
            job=self.launch(item,task,p.get('preferred_node') if task=='draft' else None)
            self.save(item,message='프로젝트의 논문 탐색부터 전체 연구를 시작합니다.' if task=='research' else 'LLM이 다음 실험을 준비합니다.',phase='job',job_id=job['id'],revision=revision)
        elif phase=='job':
            job=self.research.get(p['job_id'])
            if job['state'] in {'queued','running'}:return
            if revision!=p['revision']:
                self.save(item,message='변경된 방향을 반영해 다시 준비합니다.',phase='prepare',job_id=None);return
            discovery=Path(job['run_dir'])/'council/status.json'
            if job['config'].get('task')=='research' and discovery.is_file() and json.loads(discovery.read_text()).get('status')=='completed':
                self.save(item,discovery_completed=True,research_job_id=job['id'])
            if job['state']!='completed' or job['phase']!='experiment_approval':raise ValueError(job['message'])
            registration=json.loads((Path(job['run_dir'])/'registered-experiment.json').read_text());experiment=self.experiments.experiment(registration['id'])
            code_hash=hashlib.sha256(experiment['spec']['code'].encode()).hexdigest()
            if code_hash in p['code_hashes']:raise ValueError('동일한 코드의 반복 실행을 멈췄습니다. 새 비교나 조건을 지시하세요.')
            with self.store._connect() as conn:existing=conn.execute('SELECT * FROM experiment_runs WHERE experiment_id=? ORDER BY queued_at DESC LIMIT 1',(experiment['id'],)).fetchone()
            if existing:run=dict(existing)
            else:
                approval=self.experiments.approve(experiment['id'],experiment['digest'],True,authority='automatic:'+item['id'])
                run=self.experiments.enqueue(experiment['id'],approval['id'])
            self.save(item,message='검토된 LLM 실험을 자동 실행합니다.',phase='run',run_id=run['id'],experiment_id=experiment['id'],
                      cycles=p['cycles']+1,code_hashes=p['code_hashes']+[code_hash])
        elif phase=='run':
            run=self.experiments.run_info(p['run_id'])
            if run['state'] not in TERMINAL:return
            if run['state'] not in {'succeeded','failed','timed_out'}:raise ValueError('실험이 중단됐습니다. 로그를 확인한 뒤 재개하세요.')
            if self.research.active_id is not None:return
            experiment=self.experiments.experiment(run['experiment_id']);job=self.launch(item,'analyze',experiment['node_id'],run['id'])
            with self.store._connect() as conn:conn.execute("INSERT OR REPLACE INTO research_analysis_queue VALUES(?,'dispatched',?,NULL)",(run['id'],job['id']))
            self.save(item,message='실험 결과를 분석하고 다음 비교를 결정합니다.',phase='analysis',job_id=job['id'],
                      failures=0 if run['state']=='succeeded' else p['failures']+1)
        elif phase=='analysis':
            job=self.research.get(p['job_id'])
            if job['state'] in {'queued','running'}:return
            if job['state']!='completed' or job['phase']!='analyzed':raise ValueError(job['message'])
            result=json.loads((Path(job['run_dir'])/'analysis.json').read_text());decision=result.get('next_experiment',{})
            if result.get('outcome') not in {'measured','failed','inconclusive'} or decision.get('decision') not in {'continue','stop'}:
                raise ValueError('분석 응답의 결과·다음 실험 판단이 유효하지 않습니다. 원본 보고를 확인하세요.')
            if revision!=p['revision']:
                self.save(item,message='결과 보고를 저장했습니다. 새 방향을 반영합니다.',phase='prepare');return
            if decision['decision']=='stop':
                self.save(item,'completed','LLM이 추가 실험 중단을 제안했습니다. 결과 보고를 확인하세요.');return
            if not isinstance(decision.get('design'),str) or not decision['design'].strip():raise ValueError('다음 실험의 구체적인 설계가 없습니다.')
            run=self.experiments.run_info(p['run_id'])
            failures=p['failures']+(1 if result['outcome']!='measured' and run['state']=='succeeded' else 0)
            self.save(item,message='결과 보고를 저장했습니다. LLM이 제안한 다음 실험으로 이어갑니다.',phase='prepare',failures=failures)

    def native_tick(self,item):
        p=item['progress']
        portfolio=item['config'].get('orchestration')=='hypothesis-tasks'
        if portfolio and p.get('phase')=='tasks':
            from research_tasks import tick
            return tick(self,item)
        if p.get('recovery_after',0)>time.time():return
        if p.get('job_id'):
            job=self.research.get(p['job_id'])
            if job['state'] in {'queued','running'}:return
            if portfolio and job['state']=='completed' and job['config'].get('task_role')=='discovery':
                from research_tasks import listing
                selected=[t for t in listing(self.store,item['id']) if t['round']==p.get('native_cycle',0)]
                self.save(item,message='탐색 가설을 독립 연구 작업으로 전달했습니다.' if selected else '새 가설 근거를 보강하며 다음 분야를 탐색합니다.',phase='tasks' if selected else 'prepare',job_id=None,native_cycle=p.get('native_cycle',0) if selected else p.get('native_cycle',0)+1)
                return
            if job['state']=='completed' and job['phase']=='native-completed':
                message='자율 연구의 실험·Reviewer·Council 평가와 최종 보고를 완료했습니다.'
                if item['config'].get('research_style')=='scout':
                    done=json.loads((Path(job['run_dir'])/'native-completion.json').read_text());completed=done.get('completed_experiments',len(done.get('run_ids',[])));message='탐색 완료 · 유망 후보 '+str(done.get('promising_count',0))+'개 · 정상 측정 '+str(completed)+'회 · 전체 시도 '+str(len(done.get('run_ids',[])))+'회'
                if item['config'].get('execution_policy')=='until_deadline':
                    archive=Path(job['run_dir'])/'cycle-artifacts';archive.mkdir(exist_ok=True)
                    for name in ['LITERATURE.md','source-evidence.json','candidate_papers.json','SCOUT_IDEAS.md','NARRATIVE_REPORT.md','reviewer-latest.json']:
                        source=Path(item['config']['native_workspace'])/name
                        if source.is_file() and not source.is_symlink():shutil.copy2(source,archive/name)
                    cycle=p.get('native_cycle',0)+1
                    self.save(item,message=message+' · 다음 탐색을 계속합니다.',phase='prepare',job_id=None,native_cycle=cycle,cycles_completed=p.get('cycles_completed',0)+1,recovery_after=0)
                    return
                self.save(item,'completed',message)
                return
            if p.get('phase')=='native':
                error=job.get('error') or job['message']
                if any(term in error.lower() for term in ['인증','로그인','unauthorized','authentication','설치가 필요합니다']):raise ValueError(error)
                from session_budget import update
                update(item['config']['session_budget'],'check')
                _,assignment=self.experiments._resources(self.root(item['project_id']))
                with self.store._connect() as conn:budget=self.experiments._budget(item['project_id'],assignment['updated_at'],assignment['time_budget_minutes']*60,conn)
                if budget['remaining_seconds']<1:raise ValueError('프로젝트 실행 시간 예산을 소진했습니다.')
                attempt=p.get('recovery_attempts',0)+1;delay=min(60,2**min(attempt,6))
                self.save(item,message='자동 디버깅 '+str(attempt)+'회 · '+str(delay)+'초 뒤 원래 세션을 이어갑니다.',phase='recovery',job_id=None,recovery_attempts=attempt,recovery_after=time.time()+delay,recovery_error=error,recovery_job_id=job['id'])
                self.store.add_note(item['node_id'],'analysis','자동 복구 진단','이전 작업: '+job['id']+'\n원인: '+error+'\n원본 로그: '+job['run_dir']+'\n기존 대화·장치·시간·모델 예산을 유지해 자동으로 디버깅합니다.')
                return
        if self.research.active_id is not None or self.busy(item['project_id']):return
        job=self.research.start(dict(node_id=item['node_id'],task='native',confirm=True,mode=item['config']['mode'],context_path=item['config']['context_path']),
            internal=dict(cost_profile=item['config'].get('cost_profile','standard'),auto_session_id=item['id'],session_budget=item['config']['session_budget'],native_workspace=str(Path(item['config']['native_workspace'])/'discovery'/str(p.get('native_cycle',0))) if portfolio else item['config']['native_workspace'],task_role='discovery' if portfolio else 'single',research_style=item['config'].get('research_style','focused'),scout_preferences=item['config'].get('scout_preferences',{}),execution_policy=item['config'].get('execution_policy','bounded'),deadline_epoch=item['config'].get('deadline_epoch'),native_cycle=p.get('native_cycle',0)))
        self.save(item,message='메인 자율 연구 세션이 탐색·구현·실험·리뷰를 이어갑니다.',phase='native',job_id=job['id'],recovery_after=0)

    def _loop(self):
        while not self.closed.wait(.5):
            with self.lock:
                self._conversation_requests()
                with self.store._connect() as conn:items=[self.decode(r) for r in conn.execute("SELECT * FROM automatic_sessions WHERE status='running'")]
                awake=any(i['config'].get('execution_policy')=='until_deadline' and i['config']['deadline_epoch']>time.time() for i in items)
                try:
                    if self.sleep_guard is not None and self.sleep_guard.poll() is not None:self.sleep_guard=None
                    if awake and self.sleep_guard is None and shutil.which('caffeinate'):self.sleep_guard=subprocess.Popen(['caffeinate','-i','-w',str(os.getpid())],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                    elif not awake and self.sleep_guard is not None:
                        self.sleep_guard.terminate()
                        try:self.sleep_guard.wait(timeout=1)
                        except subprocess.TimeoutExpired:self.sleep_guard.kill()
                        self.sleep_guard=None
                except OSError:self.sleep_guard=None
                for item in items:
                    try:self.tick(item)
                    except Exception as error:
                        with (Path(item['config']['session_budget']).parent/'controller.log').open('a') as log:log.write(now()+'\n'+traceback.format_exc()+'\n')
                        self.save(item,'blocked',str(error)[:1800])
                        try:self.store.add_note(item['node_id'],'memo','자동모드 · 확인 필요',str(error)[:6000])
                        except (KeyError,ValueError):pass
                try:self._restart_requests()
                except Exception:
                    with (self.research.root/'controller.log').open('a') as log:log.write(now()+'\n'+traceback.format_exc()+'\n')

    def _restart_requests(self):
        if self.research.active_id is not None:return
        with self.store._connect() as conn:rows=[dict(r) for r in conn.execute("SELECT * FROM research_directions WHERE state='restart_pending' ORDER BY seq DESC")]
        for direction in rows:
            project_id=direction['project_id']
            if self.busy(project_id):continue
            # Running/paused automatic sessions own their next step and budget.
            sessions=self.sessions(project_id)
            if sessions and sessions[0]['status'] in {'running','paused','blocked'}:continue
            if sessions and sessions[0]['config'].get('execution_policy')=='until_deadline' and time.time()>=sessions[0]['config']['deadline_epoch']:continue
            try:
                root=self.root(project_id)
                task='draft' if self.has_hypotheses(project_id) else 'research'
                prior=self.research.list(project_id)['jobs'];context=next((j['config']['context_path'] for j in prior if j['config'].get('context_path')),'')
                self.research.start(dict(node_id=direction['node_id'] if task=='draft' else root['id'],task=task,confirm=True,context_path=context))
            except (KeyError,ValueError):
                with self.store._connect() as conn:conn.execute("UPDATE research_directions SET state='blocked' WHERE seq=?",(direction['seq'],))
            break

    def close(self):
        self.closed.set()
        if self.thread.is_alive():self.thread.join(timeout=3)
        if self.sleep_guard is not None:
            self.sleep_guard.terminate()
            try:self.sleep_guard.wait(timeout=3)
            except subprocess.TimeoutExpired:self.sleep_guard.kill()
