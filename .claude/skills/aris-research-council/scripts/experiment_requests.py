"""Explicit human experiment requests; scheduling through the original study runner."""
import json
from pathlib import Path
import re
import uuid
from tree_store import now


def initialize(store):
    with store._connect() as c:c.execute('''CREATE TABLE IF NOT EXISTS experiment_requests (
        id TEXT PRIMARY KEY,project_id TEXT NOT NULL,request_id TEXT NOT NULL,
        content TEXT NOT NULL,node_id TEXT NOT NULL,session_id TEXT,
        created_at TEXT NOT NULL,UNIQUE(project_id,request_id))''')


def parse(text):
    match=re.fullmatch(r'(?:새\s*실험|실험\s*추가|new\s+experiment)\s*[:：]\s*(.*)',text.strip(),re.I|re.S)
    return match[1].strip() if match else None


def add(controller,project_id,content,request_id):
    if not isinstance(content,str) or not content.strip() or len(content)>6000:raise ValueError('새 실험: 검증할 내용 형식으로 1–6000자를 입력하세요.')
    if not isinstance(request_id,str) or not re.fullmatch(r'[a-zA-Z0-9-]{16,80}',request_id):raise ValueError('실험 요청 ID를 확인하세요.')
    store=controller.store;content=content.strip();initialize(store)
    with controller.lock:
        root=controller.root(project_id);store.get_node(root['id'])
        identity=str(uuid.uuid5(uuid.NAMESPACE_URL,project_id+':experiment-request:'+request_id))
        node_id=str(uuid.uuid5(uuid.NAMESPACE_URL,identity+':hypothesis'))
        with store._connect() as c:
            c.execute('BEGIN IMMEDIATE')
            old=c.execute('SELECT * FROM experiment_requests WHERE project_id=? AND request_id=?',(project_id,request_id)).fetchone()
            if old:
                if old['content']!=content:raise ValueError('같은 실험 요청 ID의 내용은 바꿀 수 없습니다.')
            else:
                if root['status'] in {'held','discarded'}:raise ValueError('연구 문제를 활성화한 뒤 실험을 추가하세요.')
                if store.max_depth is not None and root['depth']+1>store.max_depth:raise ValueError('연구 트리 깊이 한도를 확인하세요.')
                stamp=now();title=' '.join(content.split())[:120]
                metadata=dict(experiment_request_id=identity,human_requested=True,experiment_request=content,
                    novelty_status='unverified',validation_required='공식 연구 파이프라인에서 선행연구·신규성·최소 반증 실험·코드 리뷰를 먼저 검증하세요. 사용자 요청은 검증된 가설이나 측정 결과가 아닙니다.')
                c.execute('INSERT INTO nodes VALUES(?,?,?,?,?,?,?,?,?,?,?)',(node_id,root['id'],title,'hypothesis',root['depth']+1,'[]',json.dumps(metadata,ensure_ascii=False),'active',100,stamp,stamp))
                c.execute('INSERT INTO node_projects VALUES(?,?)',(node_id,project_id))
                c.execute("UPDATE nodes SET status='expanded',updated_at=? WHERE id=?",(stamp,root['id']))
                c.execute('INSERT INTO experiment_requests VALUES(?,?,?,?,?,?,?)',(identity,project_id,request_id,content,node_id,None,stamp))
                c.execute('INSERT INTO notes VALUES(?,?,?,?,?,?)',(str(uuid.uuid4()),node_id,'experiment','사용자 실험 요청',content,stamp))
                store._event(c,node_id,'created',dict(parent_id=root['id'],depth=root['depth']+1))
                store._event(c,node_id,'experiment_requested',dict(request_id=identity,novelty_status='unverified'))
        sessions=controller.sessions(project_id)
        if sessions:activate(controller,sessions[0])
        return dict(id=identity,node_id=node_id,session_status=sessions[0]['status'] if sessions else None)


def activate(controller,item):
    """Bind saved requests to a session without starting/resuming that session."""
    from research_tasks import initialize as tasks_initialize
    from project_session import identity
    store=controller.store;initialize(store);tasks_initialize(store)
    with store._connect() as c:rows=[dict(r) for r in c.execute('SELECT * FROM experiment_requests WHERE project_id=? AND (session_id IS NULL OR session_id=?)',(item['project_id'],item['id']))]
    for row in rows:
        with store._connect() as c:exists=c.execute('SELECT id FROM research_tasks WHERE id=?',(row['id'],)).fetchone()
        if exists:continue
        node=store.get_node(row['node_id'])
        work=Path(identity(store,item['project_id'])['path'])/'tasks'/row['id'];work.mkdir(parents=True,mode=0o700,exist_ok=True)
        (work/'HYPOTHESIS.json').write_text(json.dumps(node,ensure_ascii=False,indent=2))
        with store._connect() as c:
            c.execute('INSERT OR IGNORE INTO research_tasks VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(row['id'],item['id'],item['project_id'],node['id'],item['progress'].get('native_cycle',0),'queued',None,str(work),'[]',0,0,now(),now(),'사용자 실험 요청 · 공식 파이프라인 검증 대기'))
            c.execute('UPDATE experiment_requests SET session_id=? WHERE id=?',(item['id'],row['id']))
        store.update_node(node['id'],metadata=dict(research_task_id=row['id']))


def pending(store,session_id):
    initialize(store)
    with store._connect() as c:return bool(c.execute("SELECT 1 FROM experiment_requests q JOIN research_tasks t ON t.id=q.id JOIN nodes n ON n.id=q.node_id WHERE t.session_id=? AND (t.state='running' OR t.state='queued' AND n.status IN ('active','expanded'))",(session_id,)).fetchone())


def reply(result):
    text='새 실험을 추가했습니다. 작업 ID: '+result['id'][:8]+'\n공식 연구 파이프라인이 근거 확인 → 실험 설계 → 코드 작성·리뷰 → 실행·분석을 진행합니다.'
    if result['session_status']=='running':return text+'\n진행 중인 작업을 유지하고, 기존 GPU·남은 시간·사용량 한도 안에서 이어갑니다.'
    if result['session_status'] is None:return text+'\n요청만 저장했습니다. CLI에서 장치와 연구 시간을 설정해 자동 연구를 시작하세요.'
    return text+'\n현재 연구는 실행하지 않고 요청만 저장했습니다. 재개 1시간 사용량 10%p처럼 보내면 기존 설정으로 이어갑니다.'
