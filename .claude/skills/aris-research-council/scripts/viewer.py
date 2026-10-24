"""Loopback-only research tree viewer, with explicit CSRF/origin checks."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import threading
from urllib.parse import urlsplit, parse_qs

from tree_store import TreeStore
from provider_status import ProviderStatus
from compute import ComputeSettings

ASSET = Path(__file__).resolve().parent.parent / 'assets' / 'viewer.html'


class ViewerServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, store, port=8766):
        self.store = store
        self.provider_status = ProviderStatus()
        self.compute = ComputeSettings(Path(store.db_path).with_name('compute.json'))
        self.csrf = secrets.token_urlsafe(32)
        self.mutation_lock = threading.Lock()
        self.snapshot_path = Path(store.db_path).with_suffix(".json")
        super().__init__(('127.0.0.1', port), ViewerHandler)
        actual_port = self.server_address[1]
        self.allowed_hosts = {'127.0.0.1:' + str(actual_port), 'localhost:' + str(actual_port)}

    def compute_state(self):
        state=self.compute.state()
        tree=self.store.export_json()
        active={p['id'] for p in tree['projects'] if not p.get('deleted_at')}
        state['assignments']={k:v for k,v in state['assignments'].items() if k in active}
        profiles={p['id'] for p in state['profiles']}
        for node in tree['nodes']:
            saved=node['metadata'].get('compute_assignment')
            if node['project_id'] in active and node['parent_id'] is None and isinstance(saved,dict) and saved.get('profile_id') in profiles:
                state['assignments'].setdefault(node['project_id'],saved)
        return state


class ViewerHandler(BaseHTTPRequestHandler):
    server_version = 'BrainDanceViewer/1'

    def log_message(self, format, *args):
        # Do not log request bodies, tokens, evidence, or terminal control characters.
        import sys
        sys.stderr.write('viewer: %s %s\n' % (self.command, self.path.encode('unicode_escape').decode()[:200]))

    def _reply(self, code, body, content_type='application/json; charset=utf-8'):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False, allow_nan=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy',
                         "default-src 'self'; script-src 'nonce-" + self.server.csrf +
                         "'; style-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(body)

    def _trusted_host(self):
        if self.headers.get('Host') not in self.server.allowed_hosts:
            self._reply(403, {'error': 'Loopback Host required'})
            return False
        return True

    def do_GET(self):
        if not self._trusted_host():
            return
        path = urlsplit(self.path).path
        if path == '/api/tree':
            self._reply(200, self.server.store.export_json())
        elif path == '/api/providers':
            self._reply(200, self.server.provider_status.get())
        elif path == '/api/compute':
            self._reply(200, self.server.compute_state())
        elif path == '/api/messages':
            node_id = parse_qs(urlsplit(self.path).query).get('node_id', [''])[0]
            tree = self.server.store.export_json()
            nodes = {n['id']: n for n in tree['nodes']}
            if node_id not in nodes:
                self._reply(404, {'error': 'Unknown node'})
                return
            deleted={p['id'] for p in tree['projects'] if p.get('deleted_at')}
            if nodes[node_id]['project_id'] in deleted:
                self._reply(404,{'error':'프로젝트가 휴지통에 있습니다.'})
                return
            related = {node_id}
            while True:
                children = {n['id'] for n in nodes.values() if n['parent_id'] in related}
                if children <= related:
                    break
                related.update(children)
            runs = {e['run_id'] for e in tree['evaluations'] if e['node_id'] in related}
            current = nodes[node_id]
            while current:
                runs.update(str(current['metadata'][k]) for k in ('run', 'council_run') if current['metadata'].get(k))
                current = nodes.get(current['parent_id'])
            self._reply(200, {'messages': self.server.store.get_messages(sorted(runs))})
        elif path in {'/', '/viewer.html'}:
            html = ASSET.read_text(encoding='utf-8').replace('__CSRF_TOKEN__', self.server.csrf)
            self._reply(200, html.encode('utf-8'), 'text/html; charset=utf-8')
        else:
            self._reply(404, {'error': 'Not found'})

    def do_POST(self):
        if not self._trusted_host():
            return
        origin = self.headers.get('Origin')
        token = self.headers.get('X-CSRF-Token', '')
        if origin != 'http://' + self.headers['Host'] or not secrets.compare_digest(token, self.server.csrf):
            self._reply(403, {'error': 'Same-origin request and CSRF token required'})
            return
        if self.headers.get('Content-Type', '').split(';')[0].strip() != 'application/json':
            self._reply(415, {'error': 'application/json required'})
            return
        try:
            length = int(self.headers.get('Content-Length', '-1'))
            if not 0 < length <= 262144:
                self._reply(413, {'error': 'Request body must be 1–262144 bytes'})
                return
            payload = json.loads(self.rfile.read(length), parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))
            if not isinstance(payload, dict):
                raise ValueError('Request body must be an object')
            path = urlsplit(self.path).path
            with self.server.mutation_lock:
                self._mutate(path, payload)
        except KeyError as exc:
            self._reply(404, {'error': str(exc)})
        except (ValueError, TypeError, OverflowError) as exc:
            self._reply(400, {'error': str(exc)})

    def _mutate(self, path, payload):
        if path in {'/api/project/delete','/api/project/restore'}:
            if set(payload)!={'project_id'}:
                raise ValueError('Expected project_id')
            result=self.server.store.set_project_deleted(payload['project_id'],path.endswith('/delete'))
        elif path == '/api/project':
            if set(payload)!={'name','goal','compute'}:
                raise ValueError('프로젝트 이름, 연구 목표와 실행 환경을 입력하세요.')
            name,goal=payload['name'],payload['goal']
            if not isinstance(name,str) or not name.strip() or len(name)>120:
                raise ValueError('프로젝트 이름은 1–120자로 입력하세요.')
            if not isinstance(goal,str) or len(goal)>2000:
                raise ValueError('연구 목표는 최대 2000자로 입력하세요.')
            if not isinstance(payload['compute'],dict):
                raise ValueError('실행 환경을 선택하세요.')
            assignment=self.server.compute.prepare_assignment(payload['compute'])
            node=self.server.store.add_node(None,goal.strip() or name.strip(),kind='problem',project_title=name,
                metadata={'project_name':name.strip(),'research_goal':goal.strip(),'compute_assignment':assignment})
            result={'node':node,'project_id':node['project_id'],'assignment':assignment}
            try:
                self.server.compute.persist_assignment(node['project_id'],assignment)
            except OSError:
                # SQLite already contains the complete project and assignment; GET recovers it.
                result['warning']='프로젝트는 저장했습니다. 실행 환경 JSON 복제본은 다시 저장해야 합니다.'
        elif path == '/api/compute/profile':
            result=self.server.compute.save_profile(payload)
        elif path == '/api/compute/probe':
            if set(payload)!={'profile_id'}: raise ValueError('Expected profile_id')
            result=self.server.compute.probe(payload['profile_id'])
        elif path == '/api/compute/assignment':
            project_id=payload.pop('project_id',None)
            if project_id not in {p['id'] for p in self.server.store.export_json()['projects'] if not p.get('deleted_at')}:
                raise ValueError('프로젝트를 선택하세요.')
            result=self.server.compute.assign(project_id,payload)
        elif path == '/api/node':
            allowed = {'id', 'title', 'status', 'priority', 'metadata'}
            if set(payload) - allowed or not isinstance(payload.get('id'), str):
                raise ValueError('Expected id and status/priority/metadata only')
            result = self.server.store.update_node(payload.pop('id'), **payload)
        elif path == '/api/note':
            if set(payload) != {'node_id', 'kind', 'title', 'content'}:
                raise ValueError('Expected node_id, kind, title, content')
            result = self.server.store.add_note(**payload)
        elif path == '/api/branch':
            allowed = {'parent_id', 'title', 'kind', 'evidence', 'metadata', 'status', 'priority'}
            if set(payload) - allowed or 'title' not in payload or 'parent_id' not in payload:
                raise ValueError('Expected parent_id, title and supported node fields')
            if payload['parent_id'] is not None and not isinstance(payload['parent_id'], str):
                raise ValueError('parent_id must be a string or null')
            result = self.server.store.add_node(**payload)
        else:
            self._reply(404, {'error': 'Not found'})
            return
        try:
            self.server.store.export_json(self.server.snapshot_path)
        except (OSError, ValueError):
            import traceback
            traceback.print_exc()
            if path == '/api/project':
                result['warning']='프로젝트는 SQLite에 저장했습니다. JSON 내보내기는 다시 확인해야 합니다.'
                self._reply(200,result)
                return
            self._reply(500, {'error': 'Saved in SQLite; JSON snapshot failed. Check the viewer log.'})
            return
        self._reply(200, result)

def create_server(db_path, port=8766, max_depth=None):
    return ViewerServer(TreeStore(db_path, max_depth=max_depth), port)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', required=True)
    parser.add_argument('--port', type=int, default=8766)
    parser.add_argument('--max-depth', type=int, default=3)
    args = parser.parse_args()
    with create_server(args.db, args.port, args.max_depth) as server:
        print('BrainDance Viewer: http://127.0.0.1:%d' % server.server_address[1], flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
