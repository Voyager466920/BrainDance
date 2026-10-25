"""Transactional research tree. SQLite is authoritative; JSON is an atomic snapshot."""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import uuid
from datetime import datetime, timezone

STATUSES = {'active', 'expanded', 'held', 'discarded'}


def now():
    return datetime.now(timezone.utc).isoformat()


class TreeStore:
    def __init__(self, db_path, max_depth=None):
        self.db_path = str(Path(db_path).expanduser().resolve())
        if max_depth is not None and (type(max_depth) is not int or max_depth < 0):
            raise ValueError('max_depth must be a nonnegative integer')
        self.max_depth = max_depth
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS nodes (
                    id TEXT PRIMARY KEY, parent_id TEXT REFERENCES nodes(id),
                    title TEXT NOT NULL, kind TEXT NOT NULL, depth INTEGER NOT NULL,
                    evidence TEXT NOT NULL, metadata TEXT NOT NULL,
                    status TEXT NOT NULL, priority INTEGER NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS evaluations (
                    id TEXT PRIMARY KEY, node_id TEXT NOT NULL REFERENCES nodes(id),
                    run_id TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, node_id TEXT REFERENCES nodes(id),
                    action TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS notes (
                    id TEXT PRIMARY KEY, node_id TEXT NOT NULL REFERENCES nodes(id),
                    kind TEXT NOT NULL, title TEXT NOT NULL, content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY, run_id TEXT NOT NULL, round INTEGER NOT NULL,
                    phase TEXT NOT NULL, participant TEXT NOT NULL, direction TEXT NOT NULL,
                    content TEXT NOT NULL, source TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS node_projects (
                    node_id TEXT PRIMARY KEY REFERENCES nodes(id),
                    project_id TEXT NOT NULL REFERENCES projects(id)
                );
                CREATE TABLE IF NOT EXISTS project_lifecycle (
                    project_id TEXT PRIMARY KEY REFERENCES projects(id), deleted_at TEXT
                );
            ''')
            # Existing trees become projects without changing any node or decision.
            conn.execute('INSERT OR IGNORE INTO projects SELECT id,title,created_at,updated_at FROM nodes WHERE parent_id IS NULL')
            conn.execute('''WITH RECURSIVE family(id,project_id) AS (
                SELECT id,id FROM nodes WHERE parent_id IS NULL
                UNION ALL SELECT n.id,f.project_id FROM nodes n JOIN family f ON n.parent_id=f.id
            ) INSERT OR IGNORE INTO node_projects SELECT id,project_id FROM family''')

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    @staticmethod
    def _decode(row):
        result = dict(row)
        for field in ('evidence', 'metadata', 'payload'):
            if field in result:
                result[field] = json.loads(result[field])
        return result

    @staticmethod
    def _event(conn, node_id, action, payload):
        conn.execute('INSERT INTO events(node_id,action,payload,created_at) VALUES(?,?,?,?)',
                     (node_id, action, json.dumps(payload, ensure_ascii=False), now()))

    def get_node(self, node_id):
        with self._connect() as conn:
            self._ensure_active(conn,node_id)
            row = conn.execute('SELECT n.*,p.project_id FROM nodes n LEFT JOIN node_projects p ON p.node_id=n.id WHERE n.id=?', (node_id,)).fetchone()
            if row is None:
                raise KeyError('Unknown node: ' + str(node_id))
            return self._decode(row)

    @staticmethod
    def _ensure_active(conn,node_id):
        row=conn.execute('SELECT l.deleted_at FROM node_projects n JOIN project_lifecycle l ON n.project_id=l.project_id WHERE n.node_id=?',(node_id,)).fetchone()
        if row and row['deleted_at']:
            raise ValueError('휴지통에 있는 프로젝트입니다. 먼저 복원하세요.')

    def set_project_deleted(self,project_id,deleted):
        if not isinstance(project_id,str) or type(deleted) is not bool:
            raise ValueError('Invalid project action')
        with self._connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            if conn.execute('SELECT id FROM projects WHERE id=?',(project_id,)).fetchone() is None:
                raise KeyError('Unknown project')
            previous=conn.execute('SELECT deleted_at FROM project_lifecycle WHERE project_id=?',(project_id,)).fetchone()
            deleted_at=(previous['deleted_at'] if previous and previous['deleted_at'] else now()) if deleted else None
            conn.execute('INSERT INTO project_lifecycle VALUES(?,?) ON CONFLICT(project_id) DO UPDATE SET deleted_at=excluded.deleted_at',(project_id,deleted_at))
            if bool(previous and previous['deleted_at'])!=deleted:
                root=conn.execute('SELECT n.id FROM nodes n JOIN node_projects p ON p.node_id=n.id WHERE p.project_id=? AND n.parent_id IS NULL',(project_id,)).fetchone()
                self._event(conn,root['id'] if root else None,'project_deleted' if deleted else 'project_restored',{'project_id':project_id})
        return dict(project_id=project_id,deleted_at=deleted_at)

    def add_node(self, parent_id, title, kind='hypothesis', evidence=None,
                 metadata=None, status='active', priority=0, project_title=None):
        if project_title is not None and (parent_id is not None or not isinstance(project_title,str) or not project_title.strip() or len(project_title)>120):
            raise ValueError('프로젝트 이름은 1–120자로 입력하세요.')
        if not isinstance(title, str) or not title.strip() or len(title) > 2000:
            raise ValueError('title must contain 1–2000 characters')
        if not isinstance(kind, str) or not kind.strip() or len(kind) > 100:
            raise ValueError('kind must contain 1–100 characters')
        evidence = [] if evidence is None else evidence
        metadata = {} if metadata is None else metadata
        self._validate(status, priority, metadata)
        if not isinstance(evidence, list):
            raise ValueError('evidence must be an array')
        evidence_json = json.dumps(evidence, ensure_ascii=False, allow_nan=False)
        metadata_json = json.dumps(metadata, ensure_ascii=False, allow_nan=False)
        node_id, timestamp = str(uuid.uuid4()), now()
        with self._connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            depth = 0
            if parent_id is not None:
                self._ensure_active(conn,parent_id)
                parent = conn.execute('SELECT * FROM nodes WHERE id=?', (parent_id,)).fetchone()
                if parent is None:
                    raise KeyError('Unknown parent: ' + str(parent_id))
                if parent['status'] in {'held', 'discarded'}:
                    raise ValueError('Reactivate the parent before expanding it')
                depth = parent['depth'] + 1
            if self.max_depth is not None and depth > self.max_depth:
                raise ValueError('Research tree depth limit exceeded')
            conn.execute('INSERT INTO nodes VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                         (node_id, parent_id, title.strip(), kind.strip(), depth,
                          evidence_json, metadata_json, status, priority, timestamp, timestamp))
            if parent_id is None:
                project_id = node_id
                conn.execute('INSERT INTO projects VALUES(?,?,?,?)', (project_id,(project_title or title).strip(),timestamp,timestamp))
            else:
                project_id = conn.execute('SELECT project_id FROM node_projects WHERE node_id=?', (parent_id,)).fetchone()[0]
            conn.execute('INSERT INTO node_projects VALUES(?,?)', (node_id,project_id))
            if parent_id is not None:
                conn.execute('UPDATE nodes SET status=?,updated_at=? WHERE id=?',
                             ('expanded', timestamp, parent_id))
                self._event(conn, parent_id, 'expanded', {'child_id': node_id})
            self._event(conn, node_id, 'created', {'parent_id': parent_id, 'depth': depth})
        return self.get_node(node_id)

    @staticmethod
    def _validate(status, priority, metadata):
        if not isinstance(status, str) or status not in STATUSES:
            raise ValueError('Invalid status')
        if type(priority) is not int or not -1000 <= priority <= 1000:
            raise ValueError('priority must be an integer between -1000 and 1000')
        if not isinstance(metadata, dict):
            raise ValueError('metadata must be an object')

    def update_node(self, node_id, status=None, priority=None, metadata=None, title=None):
        """Shallow-merge metadata; parent/depth are immutable, so no reparenting cycles."""
        with self._connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            self._ensure_active(conn,node_id)
            row = conn.execute('SELECT * FROM nodes WHERE id=?', (node_id,)).fetchone()
            if row is None:
                raise KeyError('Unknown node: ' + str(node_id))
            node = self._decode(row)
            if title is not None and (not isinstance(title, str) or not title.strip() or len(title) > 2000):
                raise ValueError('title must contain 1–2000 characters')
            next_status = node['status'] if status is None else status
            next_priority = node['priority'] if priority is None else priority
            if metadata is not None and not isinstance(metadata, dict):
                raise ValueError('metadata must be an object')
            next_metadata = dict(node['metadata'])
            next_metadata.update(metadata or {})
            self._validate(next_status, next_priority, next_metadata)
            encoded = json.dumps(next_metadata, ensure_ascii=False, allow_nan=False)
            conn.execute('UPDATE nodes SET title=?,status=?,priority=?,metadata=?,updated_at=? WHERE id=?',
                         (node['title'] if title is None else title.strip(), next_status, next_priority, encoded, now(), node_id))
            self._event(conn, node_id, 'updated', {
                'status': next_status, 'priority': next_priority, 'metadata': metadata or {},
                'title': title, 'previous_title': node['title'] if title is not None else None})
        return self.get_node(node_id)

    def add_note(self, node_id, kind, title, content):
        if kind not in {'idea', 'experiment', 'result', 'analysis', 'memo'}:
            raise ValueError('Invalid note kind')
        if not isinstance(title, str) or not title.strip() or len(title) > 300:
            raise ValueError('Note title must contain 1–300 characters')
        if not isinstance(content, str) or not content.strip() or len(content) > 100000:
            raise ValueError('Note content must contain 1–100000 characters')
        record = dict(id=str(uuid.uuid4()), node_id=node_id, kind=kind,
                      title=title.strip(), content=content, created_at=now())
        with self._connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            self._ensure_active(conn,node_id)
            if conn.execute('SELECT id FROM nodes WHERE id=?', (node_id,)).fetchone() is None:
                raise KeyError('Unknown node: ' + str(node_id))
            conn.execute('INSERT INTO notes VALUES(:id,:node_id,:kind,:title,:content,:created_at)', record)
            self._event(conn, node_id, 'note_added', {'note_id': record['id'], 'kind': kind})
        return record

    def record_message(self, record):
        """Idempotent import of actual retained requests/responses, never invented dialogue."""
        required = {'id', 'run_id', 'round', 'phase', 'participant', 'direction', 'content', 'source', 'created_at'}
        if set(record) != required or record['direction'] not in {'request', 'response'}:
            raise ValueError('Invalid transcript record')
        with self._connect() as conn:
            conn.execute('INSERT OR IGNORE INTO messages VALUES(:id,:run_id,:round,:phase,:participant,:direction,:content,:source,:created_at)', record)

    def record_evaluation(self, node_id, run_id, payload):
        if not isinstance(payload, dict) or not isinstance(run_id, str) or not run_id:
            raise ValueError('evaluation needs a run_id and object payload')
        record = {'id': str(uuid.uuid4()), 'node_id': node_id, 'run_id': run_id,
                  'payload': payload, 'created_at': now()}
        encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False)
        with self._connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            self._ensure_active(conn,node_id)
            if conn.execute('SELECT id FROM nodes WHERE id=?', (node_id,)).fetchone() is None:
                raise KeyError('Unknown node: ' + str(node_id))
            conn.execute('INSERT INTO evaluations VALUES(?,?,?,?,?)',
                         (record['id'], node_id, run_id, encoded, record['created_at']))
            self._event(conn, node_id, 'evaluated', {'evaluation_id': record['id'], 'run_id': run_id})
        return record

    def export_json(self, path=None):
        with self._connect() as conn:
            conn.execute('BEGIN')
            snapshot = {'schema_version': 7, 'exported_at': now(),
                        'projects': [dict(r) for r in conn.execute('SELECT p.*,l.deleted_at FROM projects p LEFT JOIN project_lifecycle l ON p.id=l.project_id ORDER BY p.created_at,p.id')],
                        'nodes': [self._decode(r) for r in conn.execute('SELECT n.*,p.project_id FROM nodes n LEFT JOIN node_projects p ON n.id=p.node_id ORDER BY n.created_at,n.id')],
                        'evaluations': [self._decode(r) for r in conn.execute('SELECT * FROM evaluations ORDER BY created_at,id')],
                        'events': [self._decode(r) for r in conn.execute('SELECT * FROM events ORDER BY seq')],
                        'notes': [dict(r) for r in conn.execute('SELECT * FROM notes ORDER BY created_at,id')]}
            tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            snapshot['cleanup_pending'] = [dict(r) for r in conn.execute('''SELECT project_id AS id,title,
                created_at AS deleted_at,1 AS cleanup_pending,error FROM project_cleanup_jobs ORDER BY created_at''')] if 'project_cleanup_jobs' in tables else []
            for table,fields in [('experiments',('spec',)),('experiment_runs',('result',)),('experiment_approvals',()),('research_jobs',('config',))]:
                snapshot[table]=[]
                if table in tables:
                    for row in conn.execute('SELECT * FROM '+table+' ORDER BY rowid'):
                        record=dict(row)
                        for field in fields:record[field]=json.loads(record[field])
                        snapshot[table].append(record)
        if path is not None:
            target = Path(path).expanduser().resolve()
            if target == Path(self.db_path):
                raise ValueError('JSON export cannot overwrite the SQLite database')
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=target.parent,
                                                 prefix='.' + target.name, delete=False) as stream:
                    temporary = stream.name
                    json.dump(snapshot, stream, indent=2, ensure_ascii=False, allow_nan=False)
                    stream.write('\n')
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, target)
            finally:
                if temporary and os.path.exists(temporary):
                    os.unlink(temporary)
        return snapshot

    def get_messages(self, run_ids):
        if not run_ids:
            return []
        with self._connect() as conn:
            placeholders = ','.join('?' for _ in run_ids)
            return [dict(r) for r in conn.execute(
                'SELECT * FROM messages WHERE run_id IN (' + placeholders + ') ORDER BY round,created_at,id', list(run_ids))]


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Export a Council research tree from SQLite to JSON')
    parser.add_argument('--db', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    TreeStore(args.db).export_json(args.out)
