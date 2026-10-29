"""Durable hypothesis tasks. Scheduling only; original Skills own every study."""
import json
from pathlib import Path
import shutil
import time
import uuid
from tree_store import now


def initialize(store):
    with store._connect() as c:c.execute('''CREATE TABLE IF NOT EXISTS research_tasks (
        id TEXT PRIMARY KEY,session_id TEXT NOT NULL,project_id TEXT NOT NULL,node_id TEXT NOT NULL,
        round INTEGER NOT NULL,state TEXT NOT NULL,job_id TEXT,workspace TEXT NOT NULL,
        devices TEXT NOT NULL,attempts INTEGER NOT NULL,retry_at REAL NOT NULL,
        created_at TEXT NOT NULL,updated_at TEXT NOT NULL,message TEXT NOT NULL)''')


def listing(store,session_id):
    initialize(store)
    with store._connect() as c:rows=[dict(r) for r in c.execute('SELECT t.*,n.title FROM research_tasks t JOIN nodes n ON n.id=t.node_id WHERE t.session_id=? ORDER BY t.rowid',(session_id,))]
    for row in rows:row['devices']=json.loads(row['devices'])
    return rows


def stage(server,job,session,node_ids):
    initialize(server.store)
    from experiment_requests import initialize as requests_initialize
    requests_initialize(server.store)
    if job['config'].get('task_role')!='discovery':raise ValueError('넓은 탐색 작업에서만 연구 가설을 분리할 수 있습니다.')
    if not isinstance(node_ids,list) or not 0<=len(node_ids)<=5 or len(node_ids)!=len(set(node_ids)):raise ValueError('중복되지 않은 가설을 최대 5개 선택하세요.')
    with server.store._connect() as c:old=c.execute('SELECT id FROM research_tasks WHERE session_id=? AND round=? AND id NOT IN (SELECT id FROM experiment_requests)',(session['id'],job['config'].get('native_cycle',0))).fetchall()
    if old:
        ids={r['id'] for r in old};rows=[r for r in listing(server.store,session['id']) if r['id'] in ids]
        if {r['node_id'] for r in rows}!=set(node_ids):raise ValueError('이미 분리한 가설 목록은 덮어쓰지 않습니다.')
        return rows
    nodes=[server.store.get_node(n) for n in node_ids]
    for n in nodes:
        if n['project_id']!=job['project_id'] or n['kind']!='hypothesis' or n['status']!='active' or n['metadata'].get('scout_cycle',0)!=job['config'].get('native_cycle',0) or not n['metadata'].get('novelty_recheck'):raise ValueError('현재 탐색에서 선행연구를 재검증한 활성 가설만 선택하세요.')
    for n in nodes:
        ratings=n['metadata'].get('research_ratings',{})
        if not n['metadata'].get('rating_basis') or any(type(ratings.get(k)) is not int or not 0<=ratings[k]<=100 for k in ['potential','novelty_provisional','feasibility','falsifiability']):raise ValueError('선정 가설의 평가 점수와 근거를 먼저 기록하세요.')
    from project_session import identity
    root=Path(identity(server.store,job['project_id'])['path'])/'tasks'
    source=Path(job['config']['native_workspace'])
    for n in nodes:
        task_id=str(uuid.uuid4());work=root/task_id;work.mkdir(parents=True,mode=0o700)
        for name in ['LITERATURE.md','source-evidence.json','candidate_papers.json']:
            if (source/name).is_file():shutil.copy2(source/name,work/name)
        if (source/'idea-stage').is_dir():shutil.copytree(source/'idea-stage',work/'idea-stage')
        (work/'HYPOTHESIS.json').write_text(json.dumps(n,ensure_ascii=False,indent=2))
        with server.store._connect() as c:c.execute('INSERT INTO research_tasks VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(task_id,session['id'],job['project_id'],n['id'],job['config'].get('native_cycle',0),'queued',None,str(work),'[]',0,0,now(),now(),'공식 연구 파이프라인 실행 대기'))
        server.store.update_node(n['id'],metadata=dict(research_task_id=task_id))
    return [r for r in listing(server.store,session['id']) if r['node_id'] in node_ids]


def update(store,task_id,**values):
    values['updated_at']=now()
    with store._connect() as c:c.execute('UPDATE research_tasks SET '+','.join(k+'=?' for k in values)+' WHERE id=?',(*values.values(),task_id))


def slots(assignment):
    devices=assignment['device_ids'];count=min(4,assignment['max_parallel_runs'])
    # A physical GPU stays exclusive. One selected GPU means sequential studies.
    return [devices] * count if devices==['cpu'] else [[d] for d in devices[:count]]


def tick(controller,item):
    server=controller;store=server.store;p=item['progress'];rows=listing(store,item['id'])
    from experiment_requests import initialize as requests_initialize
    requests_initialize(store)
    with store._connect() as c:requested={r['id']:r['status'] for r in c.execute('SELECT q.id,n.status FROM experiment_requests q JOIN nodes n ON n.id=q.node_id WHERE q.session_id=?',(item['id'],))}
    def eligible(r):return r['id'] not in requested or r['state']!='queued' or requested[r['id']] in {'active','expanded'}
    def selected(rows):return sorted([r for r in rows if eligible(r) and (r['round']==p.get('native_cycle',0) or r['id'] in requested and r['state'] in {'queued','running'})],key=lambda r:r['id'] not in requested)
    current=selected(rows)
    processed={r['id'] for r in current}
    for task in current:
        if task['state']!='running':continue
        job=server.research.get(task['job_id'])
        if job['state'] in {'queued','running'}:continue
        if job['state']=='completed' and job['phase']=='native-completed':
            receipt=Path(job['run_dir'])/'native-completion.json';done=json.loads(receipt.read_text()) if receipt.is_file() else {}
            rejected=done.get('outcome')=='rejected'
            update(store,task['id'],state='rejected' if rejected else 'completed',message='실험 전 기각 · '+done.get('reason','') if rejected else '공식 연구의 실험·Reviewer 검토·결과 보고 완료')
        else:
            error=job.get('error') or job['message'];n=task['attempts']+1
            blocked=any(word in error.lower() for word in ['로그인','인증','unauthorized','authentication'])
            from brain_monitor import read
            delay=300 if n>=3 and read(Path(store.db_path).parent/'monitor/config.json').get('auto_repair') else min(60,2**min(n,6))
            update(store,task['id'],state='blocked' if blocked else 'queued',attempts=n,retry_at=time.time()+delay,message=error[:1500])
    current=sorted([r for r in listing(store,item['id']) if eligible(r) and (r['round']==p.get('native_cycle',0) or r['id'] in processed)],key=lambda r:r['id'] not in requested)
    if current and all(r['state']=='blocked' for r in current):
        controller.save(item,'blocked','가설 작업의 인증 문제를 확인해야 합니다. 원본 작업과 로그를 보존했습니다.');return
    if current and all(r['state'] in {'completed','rejected','stopped','blocked'} for r in current):
        controller.save(item,message='가설별 보고를 저장했습니다. 새로운 분야와 미해결 문제 탐색을 이어갑니다.',phase='prepare',job_id=None,native_cycle=p.get('native_cycle',0)+1,cycles_completed=p.get('cycles_completed',0)+1)
        return
    _,assignment=server.experiments._resources(controller.root(item['project_id']))
    running=[r for r in current if r['state']=='running'];available=slots(assignment)
    for task in running:
        if task['devices'] in available:available.remove(task['devices'])
    for task in current:
        if not available or server.research.worker_count()>=4:break
        if task['state']!='queued' or task['retry_at']>time.time():continue
        device=available.pop(0)
        config=item['config']
        job=server.research.start(dict(node_id=task['node_id'],task='native',confirm=True,mode=config['mode'],context_path=config['context_path']),internal=dict(cost_profile=config.get('cost_profile','standard'),auto_session_id=item['id'],session_budget=config['session_budget'],native_workspace=task['workspace'],research_style='focused',scout_preferences=config.get('scout_preferences',{}),execution_policy=config.get('execution_policy','bounded'),deadline_epoch=config.get('deadline_epoch'),native_cycle=p.get('native_cycle',0),task_role='study',hypothesis_task_id=task['id'],allocated_devices=device))
        update(store,task['id'],state='running',job_id=job['id'],devices=json.dumps(device),message='공식 연구 파이프라인이 이 가설을 검증합니다.')
    active=[r for r in listing(store,item['id']) if r['round']==p.get('native_cycle',0)]
    controller.save(item,message='가설별 공식 연구 · 진행 '+str(sum(r['state']=='running' for r in active))+' · 대기 '+str(sum(r['state']=='queued' for r in active)),phase='tasks')


def control(server,project_id,task_id,action):
    with server.store._connect() as c:row=c.execute('SELECT * FROM research_tasks WHERE id=? AND project_id=?',(task_id,project_id)).fetchone()
    if not row:raise ValueError('이 프로젝트의 가설 작업이 아닙니다.')
    if action not in {'stop','resume'}:raise ValueError('가설 작업 중지 또는 재개를 선택하세요.')
    if action=='resume' and row['state'] not in {'stopped','blocked'}:raise ValueError('중지되거나 막힌 작업을 재개하세요.')
    if action=='resume':update(server.store,task_id,state='queued',job_id=None,retry_at=0,message='기존 가설 작업공간에서 재개 대기')
    else:
        update(server.store,task_id,state='stopped',message='사용자가 이 가설 작업을 중지했습니다.')
        if row['job_id']:server.research.stop(row['job_id'])
        with server.store._connect() as c:runs=[dict(r) for r in c.execute("SELECT r.id,e.spec FROM experiment_runs r JOIN experiments e ON e.id=r.experiment_id WHERE r.project_id=? AND r.state IN ('queued','running')",(project_id,))]
        for r in runs:
            if json.loads(r['spec']).get('generation',{}).get('hypothesis_task_id')==task_id:server.experiments.cancel(r['id'])
    return dict(id=task_id,state='stopped' if action=='stop' else 'queued')
