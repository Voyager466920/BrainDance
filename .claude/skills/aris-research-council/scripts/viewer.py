"""Loopback-only research tree viewer, with explicit CSRF/origin checks."""
import argparse
import hashlib
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import shutil
import signal
import sys
import threading
from urllib.parse import urlsplit, parse_qs, quote

from tree_store import TreeStore
from provider_status import ProviderStatus
from compute import ComputeSettings
from experiments import ExperimentEngine
from project_cleanup import ProjectCleanup
from research import ResearchEngine
from autopilot import Autopilot
from research_chat import ResearchChat
from notion_reports import PublicationService
from research_reports import report_html

ASSET = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent.parent)) / 'assets' / 'viewer.html'


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
        try:
            self.experiments=ExperimentEngine(store,self.compute,self.compute_state)
            self.research=ResearchEngine(store,self.experiments)
            self.autopilot=Autopilot(store,self.research,self.experiments)
            self.chat=ResearchChat(store,self.research,self.autopilot)
            self.publications=PublicationService(store)
            self.chat.publications=self.publications
            self.cleanup=ProjectCleanup(store,self.experiments,self.compute,self.research)
        except Exception:
            if hasattr(self,'publications'):self.publications.close()
            if hasattr(self,'chat'):self.chat.close()
            if hasattr(self,'autopilot'):self.autopilot.close()
            if hasattr(self,'research'):self.research.close()
            if hasattr(self,'experiments'):self.experiments.close()
            super().server_close()
            raise

    def server_close(self):
        if hasattr(self,'publications'):self.publications.close()
        if hasattr(self,'chat'):self.chat.close()
        if hasattr(self,'autopilot'):self.autopilot.close()
        if hasattr(self,'research'):self.research.close()
        if hasattr(self,'experiments'):self.experiments.close()
        super().server_close()

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
        if path == '/api/health':
            self._reply(200, {'app': 'BrainDance', 'version': '0.11.4', 'pid': os.getpid(),
                             'workspace_id': hashlib.sha256(str(Path(self.server.store.db_path).resolve()).encode()).hexdigest()})
        elif path=='/api/chat':
            try:self._reply(200,self.server.chat.messages(parse_qs(urlsplit(self.path).query).get('project_id',[''])[0]))
            except (KeyError,ValueError) as error:self._reply(400,{'error':str(error)})
        elif path=='/api/control':
            try:self._reply(200,self.server.autopilot.state(parse_qs(urlsplit(self.path).query).get('project_id',[''])[0]))
            except (KeyError,StopIteration):self._reply(404,{'error':'프로젝트를 찾을 수 없습니다.'})
            except ValueError as error:self._reply(400,{'error':str(error)})
        elif path in {'/api/reports','/api/notion','/api/reports/file','/api/reports/preview'}:
            self._reports_get(path)
        elif path.startswith('/api/research'):
            self._research_get(path)
        elif path == '/api/project/trash':
            self._reply(200,self.server.cleanup.trash())
        elif path == '/api/project/purge-preview':
            try:
                project_id=parse_qs(urlsplit(self.path).query).get('project_id',[''])[0]
                self._reply(200,self.server.cleanup.preview(project_id))
            except KeyError as error:self._reply(404,{'error':str(error)})
            except (ValueError,OSError) as error:self._reply(400,{'error':str(error)})
        elif path == '/api/tree':
            self._reply(200, self.server.store.export_json())
        elif path == '/api/providers':
            self._reply(200, self.server.provider_status.get())
        elif path == '/api/compute':
            self._reply(200, self.server.compute_state())
        elif path.startswith('/api/experiment') or path.startswith('/api/run'):
            self._experiment_get(path)
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

    def _reports_get(self,path):
        query=parse_qs(urlsplit(self.path).query);project=query.get('project_id',[''])[0]
        try:
            if path in {'/api/reports','/api/notion'}:self._reply(200,self.server.publications.state(project))
            elif path=='/api/reports/preview':
                record=self.server.publications.state(project)['report']
                if record is None:raise ValueError('먼저 보고서를 만들어 주세요.')
                self._reply(200,report_html(record),'text/html; charset=utf-8')
            else:
                name=query.get('file',[''])[0]
                file=self.server.publications.file(project,query.get('digest',[''])[0],name)
                mime='image/png' if name.endswith('.png') else 'text/plain; charset=utf-8'
                self._reply(200,file.read_bytes(),mime)
        except (ValueError,KeyError) as error:self._reply(400,{'error':str(error)})

    def _experiment_get(self,path):
        query=parse_qs(urlsplit(self.path).query)
        try:
            if path=='/api/experiments':
                self._reply(200,self.server.experiments.list(query.get('node_id',[''])[0]))
            elif path=='/api/experiment-template':
                code=ASSET.with_name('experiment_template.py').read_text(encoding='utf-8')
                self._reply(200,{'title':'합성 데이터 CPU 분류 파일럿','code':code,'metric':'accuracy','direction':'maximize'})
            elif path=='/api/run':
                self._reply(200,self.server.experiments.run_info(query.get('id',[''])[0]))
            elif path=='/api/run/file':
                file=self.server.experiments.file(query.get('id',[''])[0],query.get('file',[''])[0])
                self.send_response(200)
                self.send_header('Content-Type','application/octet-stream')
                self.send_header('Content-Length',str(file.stat().st_size))
                self.send_header('Content-Disposition',"attachment; filename*=UTF-8''"+quote(file.name,safe=''))
                self.send_header('Cache-Control','no-store')
                self.send_header('X-Content-Type-Options','nosniff')
                self.end_headers()
                with file.open('rb') as stream:shutil.copyfileobj(stream,self.wfile)
            else:self._reply(404,{'error':'Not found'})
        except KeyError as error:self._reply(404,{'error':str(error)})
        except (ValueError,TypeError) as error:self._reply(400,{'error':str(error)})

    def _research_get(self,path):
        query=parse_qs(urlsplit(self.path).query)
        try:
            if path=='/api/research':
                self._reply(200,self.server.research.list(query.get('project_id',[''])[0]))
            elif path=='/api/research/job':
                self._reply(200,self.server.research.info(query.get('id',[''])[0]))
            elif path=='/api/research/file':
                file=self.server.research.file(query.get('id',[''])[0],query.get('file',[''])[0])
                self.send_response(200);self.send_header('Content-Type','application/octet-stream')
                self.send_header('Content-Length',str(file.stat().st_size));self.send_header('X-Content-Type-Options','nosniff')
                self.send_header('Content-Disposition',"attachment; filename*=UTF-8''"+quote(file.name))
                self.end_headers()
                with file.open('rb') as stream:shutil.copyfileobj(stream,self.wfile)
            else:self._reply(404,{'error':'Not found'})
        except KeyError as error:self._reply(404,{'error':str(error)})
        except (ValueError,TypeError,OSError) as error:self._reply(400,{'error':str(error)})

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
            if path in {'/api/notion/configure','/api/notion/disconnect','/api/notion/sync','/api/reports/build'}:
                self._publication_mutate(path,payload)
                return
            with self.server.mutation_lock:
                self._mutate(path, payload)
        except KeyError as exc:
            self._reply(404, {'error': str(exc)})
        except (ValueError, TypeError, OverflowError) as exc:
            self._reply(400, {'error': str(exc)})
        except OSError as exc:
            self._reply(500, {'error': '로컬 파일 작업을 완료하지 못했습니다: '+str(exc)})

    def _publication_mutate(self,path,payload):
        service=self.server.publications
        if path=='/api/notion/configure':
            if set(payload)-{'project_id','parent','token','auto_sync'}:raise ValueError('지원하지 않는 Notion 설정입니다.')
            token=payload.get('token','')
            if not isinstance(token,str) or len(token)>1000:raise ValueError('Notion 토큰을 확인하세요.')
            result=service.configure(payload.get('project_id'),payload.get('parent'),token,payload.get('auto_sync',False))
        elif path=='/api/notion/disconnect':
            if payload:raise ValueError('Expected empty object')
            result=service.disconnect()
        else:
            if set(payload)!={'project_id'}:raise ValueError('프로젝트를 선택하세요.')
            result=service.enqueue(payload['project_id'],publish=path=='/api/notion/sync')
        self._reply(200,result)

    def _mutate(self, path, payload):
        if path=='/api/providers/refresh':
            if payload:raise ValueError('Expected empty object')
            self._reply(200,self.server.provider_status.get(force=True))
            return
        elif path=='/api/chat/send':
            result=self.server.chat.send(payload)
        elif path=='/api/control/automatic':
            result=self.server.autopilot.control(payload)
        elif path=='/api/control/direction':
            result=self.server.autopilot.intervene(payload)
        elif path=='/api/research/start':
            result=self.server.research.start(payload)
        elif path=='/api/research/stop':
            if set(payload)!={'id'}:raise ValueError('Expected research job id')
            result=self.server.research.stop(payload['id'])
        elif path=='/api/experiment':
            result=self.server.experiments.create(payload)
        elif path=='/api/experiment/approve':
            if set(payload)!={'id','digest','consent'}:raise ValueError('Expected id, digest, consent')
            result=self.server.experiments.approve(payload['id'],payload['digest'],payload['consent'])
        elif path=='/api/experiment/run':
            if set(payload)!={'id','approval_id'}:raise ValueError('Expected id and approval_id')
            result=self.server.experiments.enqueue(payload['id'],payload['approval_id'])
        elif path=='/api/experiment/cancel':
            if set(payload)!={'run_id'}:raise ValueError('Expected run_id')
            result=self.server.experiments.cancel(payload['run_id'])
        elif path=='/api/project/purge':
            if set(payload)!={'project_id','confirmation_name'}:
                raise ValueError('삭제할 프로젝트와 확인한 이름이 필요합니다.')
            service=self.server.publications
            if not service.execution_lock.acquire(blocking=False):raise ValueError('보고서 처리가 완료된 뒤 삭제하세요.')
            try:
                result=self.server.cleanup.purge(payload['project_id'],payload['confirmation_name'])
                service.forget(payload['project_id'])
            finally:service.execution_lock.release()
        elif path in {'/api/project/delete','/api/project/restore'}:
            if set(payload)!={'project_id'}:
                raise ValueError('Expected project_id')
            if path.endswith('/delete') and self.server.autopilot.sessions(payload['project_id']):
                self.server.autopilot.control(dict(project_id=payload['project_id'],action='stop'))
            if path.endswith('/delete'):self.server.chat.cancel_project(payload['project_id'])
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
    def terminate(*_):raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM,terminate)
    with create_server(args.db, args.port, args.max_depth) as server:
        print('BrainDance Viewer: http://127.0.0.1:%d' % server.server_address[1], flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
