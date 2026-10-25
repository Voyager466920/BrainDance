"""Human research directions, frozen into each model job and plan receipt."""
import json
from tree_store import now


def initialize(store):
    with store._connect() as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS research_directions (
            seq INTEGER PRIMARY KEY AUTOINCREMENT,project_id TEXT NOT NULL,node_id TEXT NOT NULL,
            content TEXT NOT NULL,apply_mode TEXT NOT NULL,state TEXT NOT NULL,
            job_id TEXT,created_at TEXT NOT NULL)''')


def snapshot(store,project_id):
    with store._connect() as conn:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='research_directions'").fetchone():return dict(revision=0,directions=[])
        rows=[dict(r) for r in conn.execute('SELECT * FROM research_directions WHERE project_id=? ORDER BY seq DESC LIMIT 12',(project_id,))]
    return dict(revision=rows[0]['seq'] if rows else 0,directions=list(reversed(rows)))


def prompt_context(store,project_id):
    directions=snapshot(store,project_id)
    with store._connect() as conn:
        notes=[dict(r) for r in conn.execute("SELECT n.title,n.content,n.kind FROM notes n JOIN node_projects p ON p.node_id=n.node_id WHERE p.project_id=? AND n.kind IN ('analysis','result') ORDER BY n.created_at DESC,n.rowid DESC LIMIT 5",(project_id,))]
    from project_session import context
    return dict(**directions,shared_project_session=context(store,project_id),recent_results=[{**n,'content':n['content'][:6000]} for n in reversed(notes)])


def record(store,node_id,content,apply_mode):
    node=store.get_node(node_id)
    if node['status'] not in {'active','expanded'}:raise ValueError('활성 노드에서 방향을 수정하세요.')
    if not isinstance(content,str) or not content.strip() or len(content)>6000:raise ValueError('방향 지시는 1–6000자로 입력하세요.')
    if apply_mode not in {'next','restart'}:raise ValueError('반영 시점을 선택하세요.')
    with store._connect() as conn:
        cursor=conn.execute('INSERT INTO research_directions(project_id,node_id,content,apply_mode,state,created_at) VALUES(?,?,?,?,?,?)',
            (node['project_id'],node_id,content.strip(),apply_mode,'restart_pending' if apply_mode=='restart' else 'pending',now()))
        seq=cursor.lastrowid
        store._event(conn,node_id,'direction_changed',dict(revision=seq,apply_mode=apply_mode,content=content.strip()))
    store.add_note(node_id,'memo','사용자 방향 변경 · '+('지금 다시 준비' if apply_mode=='restart' else '다음 단계'),content.strip())
    return dict(revision=seq,project_id=node['project_id'],node_id=node_id)
