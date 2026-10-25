"""Permanent Trash deletion, limited to database records and managed local run files.

An atomic SQLite deletion leaves a durable cleanup job. File or settings failures
remain visible in Trash and can be retried after a restart. No SSH calls are made.
"""
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3

from tree_store import now


class ProjectCleanup:
    def __init__(self, store, experiments, compute):
        self.store, self.experiments, self.compute = store, experiments, compute
        self.workspace = Path(store.db_path).parent
        with store._connect() as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS project_cleanup_jobs (
                project_id TEXT PRIMARY KEY, title TEXT NOT NULL,
                paths TEXT NOT NULL, counts TEXT NOT NULL, created_at TEXT NOT NULL,
                error TEXT
            )''')

    def trash(self):
        with self.store._connect() as conn:
            projects = [dict(r) for r in conn.execute('''SELECT p.id,p.title,l.deleted_at
                FROM projects p JOIN project_lifecycle l ON l.project_id=p.id
                WHERE l.deleted_at IS NOT NULL ORDER BY l.deleted_at''')]
            for job in conn.execute('SELECT * FROM project_cleanup_jobs ORDER BY created_at'):
                projects.append(dict(id=job['project_id'], title=job['title'],
                                     deleted_at=job['created_at'], cleanup_pending=True,
                                     error=job['error']))
        return dict(projects=projects)

    @staticmethod
    def _run_refs(conn, node_ids):
        refs = set()
        for row in conn.execute('SELECT id,metadata FROM nodes'):
            if row['id'] in node_ids:
                data = json.loads(row['metadata'])
                refs.update(data[k] for k in ('run', 'council_run') if isinstance(data.get(k), str))
        for row in conn.execute('SELECT node_id,run_id FROM evaluations'):
            if row['node_id'] in node_ids:
                refs.add(row['run_id'])
        return refs

    def _plan(self, conn, project_id):
        job = conn.execute('SELECT * FROM project_cleanup_jobs WHERE project_id=?', (project_id,)).fetchone()
        if job:
            return dict(project_id=project_id, title=job['title'], paths=json.loads(job['paths']),
                        counts=json.loads(job['counts']), cleanup_pending=True)
        project = conn.execute('''SELECT p.*,l.deleted_at FROM projects p
            LEFT JOIN project_lifecycle l ON l.project_id=p.id WHERE p.id=?''', (project_id,)).fetchone()
        if project is None:
            raise KeyError('프로젝트를 찾을 수 없습니다.')
        if not project['deleted_at']:
            raise ValueError('휴지통으로 이동한 프로젝트만 영구 삭제할 수 있습니다.')
        nodes = {r['node_id'] for r in conn.execute('SELECT node_id FROM node_projects WHERE project_id=?', (project_id,))}
        counts = dict(nodes=len(nodes), notes=0, evaluations=0, messages=0, experiments=0, runs=0)
        for table in ('notes', 'evaluations'):
            counts[table] = conn.execute('SELECT count(*) FROM '+table+' WHERE node_id IN (SELECT node_id FROM node_projects WHERE project_id=?)', (project_id,)).fetchone()[0]
        runs = [dict(r) for r in conn.execute('SELECT * FROM experiment_runs WHERE project_id=?', (project_id,))]
        if any(r['state'] in {'queued', 'running'} or r['id'] in self.experiments.jobs for r in runs):
            raise ValueError('실험이 종료 처리 중입니다. 중지 또는 완료 후 다시 시도하세요.')
        paths = []
        for run in runs:
            if not re.fullmatch(r'[a-f0-9-]{36}', run['id']):
                raise ValueError('실험 폴더 식별자가 올바르지 않습니다.')
            expected = self.workspace/'experiment-runs'/run['id']
            if Path(run['run_dir']).absolute() != expected:
                raise ValueError('앱 전용 폴더 밖의 실험 경로는 자동 삭제하지 않습니다.')
            paths.append(str(expected.relative_to(self.workspace)))
        counts['runs'] = len(runs)
        counts['experiments'] = conn.execute('SELECT count(*) FROM experiments WHERE node_id IN (SELECT node_id FROM node_projects WHERE project_id=?)', (project_id,)).fetchone()[0]
        refs = self._run_refs(conn, nodes)
        other_nodes = {r['id'] for r in conn.execute('SELECT id FROM nodes')} - nodes
        other_refs = self._run_refs(conn, other_nodes)
        def identity(ref):
            return str(Path(ref).resolve()) if Path(ref).is_absolute() else ref
        shared_paths = {identity(ref) for ref in other_refs}
        exclusive = {ref for ref in refs if identity(ref) not in shared_paths}
        for ref in exclusive:
            counts['messages'] += conn.execute('SELECT count(*) FROM messages WHERE run_id=?', (ref,)).fetchone()[0]
            # Only the explicitly managed Council directory is owned by the app.
            # Arbitrary metadata/source paths must never become deletion targets.
            path = Path(ref)
            if path.is_absolute() and path.parent.resolve() == self.workspace/'council-runs' and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,120}', path.name):
                paths.append('council-runs/'+path.name)
        return dict(project_id=project_id, title=project['title'], paths=sorted(set(paths)),
                    counts=counts, cleanup_pending=False, exclusive_refs=exclusive)

    def _path(self, relative):
        path = Path(relative)
        if len(path.parts) != 2 or path.parts[0] not in {'experiment-runs', 'council-runs'} or path.name in {'.', '..'} or path.is_absolute():
            raise ValueError('관리 폴더 경로가 올바르지 않습니다.')
        parent = self.workspace/path.parts[0]
        if parent.is_symlink():
            raise ValueError('관리 폴더가 외부 심볼릭 링크입니다. 자동 삭제를 중단했습니다.')
        return self.workspace/path

    def _bytes(self, paths):
        total = 0
        seen = set()
        for relative in paths:
            root = self._path(relative)
            if root.is_symlink():
                total += root.lstat().st_size
                continue
            if not root.exists():
                continue
            candidates = [root] if root.is_file() else (Path(folder)/name for folder, _, names in os.walk(root, followlinks=False) for name in names)
            for path in candidates:
                stat = path.lstat()
                key = (stat.st_dev, stat.st_ino)
                if key not in seen:
                    seen.add(key)
                    total += stat.st_size
        return total

    def preview(self, project_id):
        with self.experiments.lock, self.store._connect() as conn:
            plan = self._plan(conn, project_id)
        return {k: v for k, v in plan.items() if k not in {'paths', 'exclusive_refs'}} | dict(local_file_bytes=self._bytes(plan['paths']))

    def purge(self, project_id, confirmation_name):
        with self.experiments.lock:
            with self.store._connect() as conn:
                conn.execute('BEGIN IMMEDIATE')
                plan = self._plan(conn, project_id)
                if confirmation_name != plan['title']:
                    raise ValueError('영구 삭제할 프로젝트 이름을 확인하세요.')
                # Reject unsafe paths before changing any database records.
                for relative in plan['paths']:
                    self._path(relative)
                before = self._bytes(plan['paths'])
                if not plan['cleanup_pending']:
                    conn.execute('INSERT INTO project_cleanup_jobs VALUES(?,?,?,?,?,NULL)',
                                 (project_id, plan['title'], json.dumps(plan['paths']), json.dumps(plan['counts']), now()))
                    conn.execute('DELETE FROM experiment_runs WHERE project_id=?', (project_id,))
                    for table in ('experiment_approvals', 'experiments'):
                        field = 'experiment_id' if table == 'experiment_approvals' else 'id'
                        conn.execute('DELETE FROM '+table+' WHERE '+field+' IN (SELECT id FROM experiments WHERE node_id IN (SELECT node_id FROM node_projects WHERE project_id=?))', (project_id,))
                    for table in ('notes', 'evaluations', 'events'):
                        conn.execute('DELETE FROM '+table+' WHERE node_id IN (SELECT node_id FROM node_projects WHERE project_id=?)', (project_id,))
                    for ref in plan['exclusive_refs']:
                        conn.execute('DELETE FROM messages WHERE run_id=?', (ref,))
                    nodes = conn.execute('SELECT n.id FROM nodes n JOIN node_projects p ON p.node_id=n.id WHERE p.project_id=? ORDER BY n.depth DESC', (project_id,)).fetchall()
                    conn.execute('DELETE FROM node_projects WHERE project_id=?', (project_id,))
                    for node in nodes:
                        conn.execute('DELETE FROM nodes WHERE id=?', (node['id'],))
                    conn.execute('DELETE FROM project_lifecycle WHERE project_id=?', (project_id,))
                    conn.execute('DELETE FROM projects WHERE id=?', (project_id,))
            error = None
            db = Path(self.store.db_path)
            original = db.stat().st_size
            reclaimed_db = 0
            try:
                self.compute.remove_assignment(project_id)
                for relative in plan['paths']:
                    path = self._path(relative)
                    if path.is_symlink() or path.is_file():
                        path.unlink()
                    elif path.exists():
                        shutil.rmtree(path)  # rmtree does not follow nested symlinks.
                # SQLite commit alone leaves free pages in the file. VACUUM reclaims them.
                with self.store._connect() as conn:
                    conn.execute('VACUUM')
                reclaimed_db = max(0, original-db.stat().st_size)
                with self.store._connect() as conn:
                    conn.execute('DELETE FROM project_cleanup_jobs WHERE project_id=?', (project_id,))
                self.store.export_json(db.with_suffix('.json'))
            except (OSError, ValueError, sqlite3.Error) as caught:
                error = str(caught)
                with self.store._connect() as conn:
                    conn.execute('''INSERT INTO project_cleanup_jobs VALUES(?,?,?,?,?,?)
                        ON CONFLICT(project_id) DO UPDATE SET error=excluded.error''',
                                 (project_id, plan['title'], json.dumps(plan['paths']), json.dumps(plan['counts']), now(), error))
                try:
                    self.store.export_json(db.with_suffix('.json'))
                except (OSError, ValueError, sqlite3.Error):
                    pass  # SQLite retains the cleanup job even if its JSON mirror is unavailable.
            try:
                removed_bytes=max(0,before-self._bytes(plan['paths']))
            except (OSError,ValueError):
                removed_bytes=0
            return dict(project_id=project_id, cleanup_pending=bool(error), error=error,
                        removed_file_bytes=removed_bytes, reclaimed_database_bytes=reclaimed_db)
