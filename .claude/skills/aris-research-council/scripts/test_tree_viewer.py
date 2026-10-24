"""No network except ephemeral loopback HTTP; no model or GPU calls."""
from concurrent.futures import ThreadPoolExecutor
import http.client
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

from tree_store import TreeStore
from viewer import create_server
from run_history import import_run


class TreeStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / 'tree.sqlite'
        self.store = TreeStore(self.db, max_depth=2)
        self.root = self.store.add_node(None, 'Camera shift', kind='problem')

    def test_persistence_evidence_evaluation_and_atomic_export(self):
        evidence = [{'title': 'Paper', 'url': 'https://arxiv.org/abs/1234.5678',
                     'quote': 'Preserve full source text\nwith unicode: 논문'}]
        node = self.store.add_node(self.root['id'], 'Calibrate visual features',
                                   evidence=evidence, metadata={'novelty': 3, 'experiment': {'control': 'frozen'}})
        payload = {'anonymous_id': 'Candidate A', 'novelty': 4, 'feasibility': 3,
                   'reasons': ['Evidence supports testing, not a result']}
        self.store.record_evaluation(node['id'], 'run-1', payload)
        reopened = TreeStore(self.db)
        self.assertEqual(reopened.get_node(node['id'])['evidence'], evidence)
        export = Path(self.temp.name) / 'nested' / 'tree.json'
        snapshot = reopened.export_json(export)
        self.assertEqual(json.loads(export.read_text()), snapshot)
        self.assertEqual(snapshot['evaluations'][0]['payload'], payload)
        self.assertEqual(snapshot['nodes'][0]['status'], 'expanded')
        self.assertTrue(any(e['action'] == 'evaluated' for e in snapshot['events']))
        with self.assertRaises(ValueError):
            reopened.export_json(self.db)
        self.assertEqual(len(reopened.export_json()['nodes']), 2)

    def test_depth_and_orphan_limits_rollback(self):
        child = self.store.add_node(self.root['id'], 'One')
        leaf = self.store.add_node(child['id'], 'Two')
        before = self.store.export_json()
        with self.assertRaises(ValueError):
            self.store.add_node(leaf['id'], 'Too deep')
        with self.assertRaises(KeyError):
            self.store.add_node('missing', 'Orphan')
        self.assertEqual(self.store.export_json()['nodes'], before['nodes'])
        self.assertEqual(self.store.export_json()['events'], before['events'])
        with self.assertRaises(TypeError):
            self.store.update_node(child['id'], parent_id=leaf['id'])

    def test_hold_discard_reactivate_prioritize_and_metadata_merge(self):
        node = self.store.add_node(self.root['id'], 'H', metadata={'novelty': 'uncertain'})
        for state in ('held', 'discarded'):
            self.store.update_node(node['id'], status=state)
            with self.assertRaises(ValueError):
                self.store.add_node(node['id'], 'Blocked child')
        changed = self.store.update_node(node['id'], status='active', priority=7,
                                         metadata={'feasibility': 'CPU pilot'})
        self.assertEqual(changed['metadata'], {'novelty': 'uncertain', 'feasibility': 'CPU pilot'})
        self.assertEqual(changed['priority'], 7)
        self.store.add_node(node['id'], 'Allowed child')
        for kwargs in ({'priority': True}, {'status': 'deleted'}, {'metadata': []}):
            with self.assertRaises(ValueError):
                self.store.update_node(node['id'], **kwargs)

    def test_concurrent_writes_and_evaluation_orphan(self):
        def write(index):
            return self.store.add_node(self.root['id'], 'H%d' % index)['id']
        with ThreadPoolExecutor(max_workers=5) as pool:
            ids = list(pool.map(write, range(20)))
        self.assertEqual(len(set(ids)), 20)
        self.assertEqual(len(self.store.export_json()['nodes']), 21)
        with self.assertRaises(KeyError):
            self.store.record_evaluation('missing', 'run-1', {})
        with self.assertRaises(ValueError):
            self.store.record_evaluation(self.root['id'], 'run-1', {'bad': float('nan')})

    def test_korean_title_and_append_only_research_journal(self):
        self.store.update_node(self.root['id'], title='카메라 변화 연구', metadata={'original_title': 'Camera shift'})
        for kind in ('idea', 'experiment', 'result', 'analysis', 'memo'):
            self.store.add_note(self.root['id'], kind, '조건과 관측', '<script>실행하지 않은 설계</script>')
        reopened = TreeStore(self.db)
        self.assertEqual(reopened.get_node(self.root['id'])['title'], '카메라 변화 연구')
        self.assertEqual(len(reopened.export_json()['notes']), 5)
        self.assertEqual(reopened.export_json()['notes'][0]['content'], '<script>실행하지 않은 설계</script>')
        with self.assertRaises(ValueError):
            self.store.add_note(self.root['id'], 'fake', '제목', '내용')
        with self.assertRaises(KeyError):
            self.store.add_note('missing', 'idea', '제목', '내용')
        with self.assertRaises(ValueError):
            self.store.update_node(self.root['id'], title=' ')

    def test_project_inheritance_and_existing_tree_migration(self):
        child=self.store.add_node(self.root['id'],'가설')
        other=self.store.add_node(None,'다른 프로젝트',kind='problem')
        self.assertEqual(child['project_id'],self.root['project_id'])
        self.assertNotEqual(other['project_id'],child['project_id'])
        with self.store._connect() as conn:
            conn.execute('DROP TABLE node_projects')
            conn.execute('DROP TABLE projects')
        migrated=TreeStore(self.db)
        snapshot=migrated.export_json()
        self.assertEqual(len(snapshot['projects']),2)
        self.assertEqual(migrated.get_node(child['id'])['project_id'],self.root['id'])

    def test_project_trash_preserves_records_blocks_writes_and_restores(self):
        child=self.store.add_node(self.root['id'],'유지할 가설')
        self.store.add_note(child['id'],'idea','기록','보존할 내용')
        self.store.record_evaluation(child['id'],'run',{'assessment':'uncertain'})
        before=self.store.export_json()
        project_id=self.root['project_id']
        self.store.set_project_deleted(project_id,True)
        self.store.set_project_deleted(project_id,True)
        reopened=TreeStore(self.db)
        snapshot=reopened.export_json()
        for key in ('nodes','notes','evaluations'):self.assertEqual(snapshot[key],before[key])
        self.assertTrue(snapshot['projects'][0]['deleted_at'])
        self.assertEqual(sum(e['action']=='project_deleted' for e in snapshot['events']),1)
        for operation in (lambda:reopened.get_node(child['id']),lambda:reopened.add_node(child['id'],'No'),
                          lambda:reopened.update_node(child['id'],priority=90),
                          lambda:reopened.add_note(child['id'],'memo','No','No'),
                          lambda:reopened.record_evaluation(child['id'],'run',{})):
            with self.assertRaises(ValueError):operation()
        reopened.set_project_deleted(project_id,False)
        self.assertEqual(reopened.get_node(child['id']),child)
        self.assertIsNone(reopened.export_json()['projects'][0]['deleted_at'])

    def test_actual_transcript_import_is_idempotent_and_excludes_private_files(self):
        run = Path(self.temp.name) / 'run'
        codex = run / 'round-1/generation/codex'
        codex.mkdir(parents=True)
        (run / 'status.json').write_text(json.dumps({'status': 'running'}))
        with self.assertRaises(ValueError):
            import_run(self.store, run)
        (run / 'status.json').write_text(json.dumps({'status': 'completed'}))
        (codex / 'request.json').write_text(json.dumps({'params': {'arguments': {'prompt': '실제 요청'}}}))
        (codex / 'response.txt').write_text('실제 응답')
        (run / 'round-1/private').mkdir()
        (run / 'round-1/private/anonymization-map.json').write_text('PRIVATE_MAPPING')
        self.assertEqual(import_run(self.store, run), 2)
        self.assertEqual(import_run(self.store, run), 2)
        messages = self.store.get_messages([str(run.resolve())])
        self.assertEqual(len(messages), 2)
        self.assertEqual({m['content'] for m in messages}, {'실제 요청', '실제 응답'})
        self.assertEqual(self.store.get_messages(['another-run']), [])
        self.assertNotIn('PRIVATE_MAPPING', json.dumps(messages))


class ViewerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.server = create_server(Path(self.temp.name) / 'tree.sqlite', port=0, max_depth=1)
        self.root = self.server.store.add_node(None, '<script>alert(1)</script>', kind='problem')
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        self.port = self.server.server_address[1]
        self.host = '127.0.0.1:%d' % self.port

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)

    def request(self, path, data=None, headers=None, raw=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        try:
            outgoing = {'Host': self.host}
            outgoing.update(headers or {})
            body = raw if raw is not None else (json.dumps(data) if data is not None else None)
            conn.request('POST' if body is not None else 'GET', path, body=body, headers=outgoing)
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            conn.close()

    def credentials(self):
        return {'Content-Type': 'application/json', 'Origin': 'http://' + self.host,
                'X-CSRF-Token': self.server.csrf}

    def test_readonly_routing_and_safe_rendering(self):
        self.assertEqual(self.server.server_address[0], '127.0.0.1')
        status, headers, html = self.request('/')
        self.assertEqual(status, 200)
        self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])
        self.assertIn(self.server.csrf.encode(), html)
        self.assertNotIn(b'<script>alert(1)</script>', html)
        self.assertNotIn(b'innerHTML', html)
        self.assertNotIn(b'Access-Control-Allow-Origin', str(headers).encode())
        status, _, body = self.request('/api/tree')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['nodes'][0]['title'], self.root['title'])
        for path in ('/../../etc/passwd', '/tree.sqlite', '/scripts/viewer.py'):
            self.assertEqual(self.request(path)[0], 404)
        self.assertEqual(self.request('/', headers={'Host': 'evil.example'})[0], 403)

    def test_mutation_csrf_origin_and_schema_boundaries(self):
        payload = {'id': self.root['id'], 'status': 'held'}
        self.assertEqual(self.request('/api/node', payload)[0], 403)
        headers = self.credentials()
        headers['Origin'] = 'https://attacker.example'
        self.assertEqual(self.request('/api/node', payload, headers)[0], 403)
        headers = self.credentials()
        headers['X-CSRF-Token'] = 'wrong'
        self.assertEqual(self.request('/api/node', payload, headers)[0], 403)
        self.assertEqual(self.server.store.get_node(self.root['id'])['status'], 'active')
        headers = self.credentials()
        self.assertEqual(self.request('/api/node', {**payload, 'parent_id': self.root['id']}, headers)[0], 400)
        self.assertEqual(self.request('/api/node', {'id': 'missing', 'status': 'held'}, headers)[0], 404)
        self.assertEqual(self.request('/api/node', headers=headers, raw='[]')[0], 400)
        self.assertEqual(self.request('/api/node', headers=headers, raw='{')[0], 400)
        self.assertEqual(self.request('/api/node', {'id': self.root['id'], 'metadata': {'x': float('nan')}}, headers)[0], 400)
        headers['Content-Type'] = 'text/plain'
        self.assertEqual(self.request('/api/node', payload, headers)[0], 415)

    def test_http_state_operations_branching_and_depth_limit(self):
        headers = self.credentials()
        payload = {'id': self.root['id'], 'status': 'held', 'priority': 4}
        self.assertEqual(self.request('/api/node', payload, headers)[0], 200)
        branch = {'parent_id': self.root['id'], 'title': 'H1', 'metadata': {'novelty': 'uncertain'}}
        self.assertEqual(self.request('/api/branch', branch, headers)[0], 400)
        self.assertEqual(self.request('/api/node', {'id': self.root['id'], 'status': 'active'}, headers)[0], 200)
        status, _, body = self.request('/api/branch', branch, headers)
        self.assertEqual(status, 200)
        child = json.loads(body)
        self.assertEqual(child['depth'], 1)
        self.assertEqual(self.request('/api/branch', {'parent_id': child['id'], 'title': 'too deep'}, headers)[0], 400)
        self.assertEqual(self.request('/api/node', {'id': child['id'], 'status': 'discarded'}, headers)[0], 200)
        self.assertEqual(self.server.store.get_node(child['id'])['status'], 'discarded')
        snapshot = json.loads(self.server.snapshot_path.read_text())
        authoritative = self.server.store.export_json()
        self.assertEqual(snapshot['nodes'], authoritative['nodes'])
        self.assertEqual(snapshot['events'], authoritative['events'])
        self.assertEqual(snapshot['evaluations'], authoritative['evaluations'])

    def test_journal_and_node_scoped_conversation_api(self):
        headers = self.credentials()
        note = dict(node_id=self.root['id'], kind='experiment', title='실험 조건', content='아직 실행하지 않음')
        self.assertEqual(self.request('/api/note', note)[0], 403)
        self.assertEqual(self.request('/api/note', note, headers)[0], 200)
        self.assertEqual(self.request('/api/node', {'id': self.root['id'], 'title': '한글 노드'}, headers)[0], 200)
        self.server.store.record_evaluation(self.root['id'], 'run-1', {})
        for run in ('run-1', 'unrelated'):
            self.server.store.record_message(dict(id=run,run_id=run,round=1,phase='generation',participant='Codex',direction='response',content=run,source='response.txt',created_at='2026'))
        status, _, body = self.request('/api/messages?node_id='+self.root['id'])
        self.assertEqual(status, 200)
        self.assertEqual([m['content'] for m in json.loads(body)['messages']], ['run-1'])
        self.assertEqual(self.request('/api/messages?node_id=missing')[0], 404)
        snapshot = json.loads(self.server.snapshot_path.read_text())
        self.assertEqual(snapshot['notes'][0]['content'], '아직 실행하지 않음')

    def test_compute_settings_preserve_csrf_project_and_device_boundaries(self):
        status,_,body=self.request('/api/compute')
        self.assertEqual(status,200)
        self.assertEqual(json.loads(body)['profiles'][0]['kind'],'local')
        payload=dict(project_id=self.root['project_id'],profile_id='local',device_ids=['cpu'])
        self.assertEqual(self.request('/api/compute/assignment',payload)[0],403)
        self.assertEqual(self.request('/api/compute/assignment',payload,self.credentials())[0],200)
        self.assertEqual(self.request('/api/compute/assignment',{**payload,'auto_run':True},self.credentials())[0],400)
        self.assertEqual(self.request('/api/compute/assignment',{**payload,'project_id':'missing'},self.credentials())[0],400)
        self.assertEqual(self.request('/api/compute/profile',dict(kind='ssh',name='Bad',host='-evil'),self.credentials())[0],400)

    def test_new_project_creates_named_group_goal_and_device_assignment(self):
        from compute import fingerprint,timestamp
        profile=self.server.compute.data['profiles'][0]
        self.server.compute.inventories['local']=dict(connected=True,fingerprint=fingerprint(profile),checked_at=timestamp(),devices=[dict(id='metal:0',name='Apple GPU',kind='metal')])
        payload=dict(name='새 연구',goal='환경 변화에 따른 정확도 비교',compute=dict(profile_id='local',device_ids=['metal:0'],max_parallel_runs=1,time_budget_minutes=15))
        self.assertEqual(self.request('/api/project',payload)[0],403)
        status,_,body=self.request('/api/project',payload,self.credentials())
        self.assertEqual(status,200)
        result=json.loads(body)
        node=result['node'];project_id=result['project_id']
        snapshot=self.server.store.export_json()
        self.assertEqual(next(p['title'] for p in snapshot['projects'] if p['id']==project_id),'새 연구')
        self.assertEqual(node['title'],payload['goal'])
        self.assertEqual(node['project_id'],project_id)
        self.assertEqual(node['metadata']['compute_assignment']['device_ids'],['metal:0'])
        self.assertEqual(self.server.compute_state()['assignments'][project_id]['time_budget_minutes'],15)
        self.assertFalse(result['assignment']['auto_run'])
        self.assertEqual(json.loads(self.server.snapshot_path.read_text())['projects'],snapshot['projects'])

    def test_invalid_project_or_gpu_creates_nothing_and_mirror_failure_recovers(self):
        valid=dict(name='연구',goal='',compute=dict(profile_id='local',device_ids=['cpu']))
        before=self.server.store.export_json()
        for payload in ({**valid,'name':' '},{**valid,'goal':'x'*2001},
                        {**valid,'compute':dict(profile_id='local',device_ids=['GPU-made-up'])},
                        {**valid,'compute':dict(profile_id='local',device_ids=['cpu'],auto_run=True)}):
            self.assertEqual(self.request('/api/project',payload,self.credentials())[0],400)
        self.assertEqual(self.server.store.export_json()['nodes'],before['nodes'])
        self.assertEqual(self.server.store.export_json()['projects'],before['projects'])
        with patch.object(self.server.compute,'persist_assignment',side_effect=OSError('mirror failure')):
            status,_,body=self.request('/api/project',valid,self.credentials())
        result=json.loads(body)
        self.assertEqual(status,200)
        self.assertIn('warning',result)
        self.assertEqual(self.server.compute_state()['assignments'][result['project_id']]['device_ids'],['cpu'])

    def test_project_delete_restore_api_and_compute_isolation(self):
        project_id=self.root['project_id'];headers=self.credentials()
        self.server.compute.assign(project_id,dict(profile_id='local',device_ids=['cpu']))
        other=self.server.store.add_node(None,'다른 프로젝트',kind='problem')
        payload={'project_id':project_id}
        self.assertEqual(self.request('/api/project/delete',payload)[0],403)
        self.assertEqual(self.request('/api/project/delete',{'project_id':'missing'},headers)[0],404)
        self.assertEqual(self.request('/api/project/delete',payload,headers)[0],200)
        tree=self.server.store.export_json()
        self.assertTrue(next(p for p in tree['projects'] if p['id']==project_id)['deleted_at'])
        self.assertFalse(next(p for p in tree['projects'] if p['id']==other['project_id'])['deleted_at'])
        self.assertNotIn(project_id,self.server.compute_state()['assignments'])
        self.assertEqual(self.request('/api/messages?node_id='+self.root['id'])[0],404)
        self.assertEqual(self.request('/api/node',{'id':self.root['id'],'status':'active'},headers)[0],400)
        self.assertEqual(self.request('/api/compute/assignment',{**payload,'profile_id':'local','device_ids':['cpu']},headers)[0],400)
        self.assertEqual(self.request('/api/project/restore',payload,headers)[0],200)
        self.assertEqual(self.server.compute_state()['assignments'][project_id]['device_ids'],['cpu'])
        self.assertEqual(self.server.store.get_node(self.root['id'])['title'],self.root['title'])


class ViewerRenderingTests(unittest.TestCase):
    def test_real_viewer_script_resolves_papers_and_selected_evaluations(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('Node is unavailable; Python runtime has no Node dependency')
        asset = Path(__file__).resolve().parent.parent / 'assets' / 'viewer.html'
        script = re.search(r'<script nonce="[^"]*">(.*?)</script>', asset.read_text(), re.S).group(1)
        fixture = {'nodes': [
            {'id': 'root', 'parent_id': None, 'title': 'Problem', 'kind': 'problem', 'depth': 0,
             'priority': 0, 'status': 'expanded', 'created_at': '1', 'metadata': {},
             'evidence': [{'id': 'P1', 'title': '<script>Paper title</script>',
                           'source': 'https://example.com/paper', 'excerpt': 'Original excerpt'}]},
            {'id': 'h', 'parent_id': 'root', 'title': 'Hypothesis', 'kind': 'hypothesis',
             'depth': 1, 'priority': 4, 'status': 'held', 'created_at': '2', 'evidence': ['P1'],
             'metadata': {'anonymous_label': 'A', 'novelty': {'assessment': 'Uncertain novelty'},
                          'feasibility': {'assessment': 'Small pilot'},
                          'experiment': {'metric': 'Accuracy', 'model_dataset_candidates': [{'model': 'ViT-tiny'}]}, 'model': 'HIDDEN_IDENTITY',
                          'author_map': {'A': 'HIDDEN_AUTHOR'}}}],
            'evaluations': [{'node_id': 'h', 'run_id': 'test', 'created_at': '3',
                'payload': {'chairman': {'label': 'A', 'status': 'held', 'priority': 4,
                                         'novelty_score': 3, 'feasibility_score': 4, 'rigor_score': 2,
                                         'rationale': 'Chairman rationale'},
                            'peer_reviews': [{'reviewer': 'Peer 1', 'evaluation': {
                                'collective_miss': 'Shared blind spot', 'evaluations': [
                                    {'label': 'A', 'novelty_score': 2, 'feasibility_score': 3,
                                     'rigor_score': 4, 'rationale': 'Selected peer rationale'},
                                    {'label': 'B', 'rationale': 'Other candidate rationale'}]}}]}}],
            'events': []}
        harness = r"""
const vm=require('vm'),assert=require('assert');
class Element {
 constructor(tag,id){this.tag=tag;this.id=id;this.children=[];this.text='';this.style={};this.dataset={};}
 set textContent(v){this.text=String(v);this.children=[];}
 get textContent(){return this.text+this.children.map(c=>c.textContent||'').join('');}
 get childNodes(){return this.children;}
 append(...c){this.children.push(...c);}
 replaceChildren(...c){this.text='';this.children=c;}
 setAttribute(key,value){this[key]=value;}
}
const elements=new Map();
const document={getElementById(id){if(!elements.has(id))elements.set(id,new Element('div',id));return elements.get(id);},createElement(tag){return new Element(tag);},createElementNS(namespace,tag){return new Element(tag);},querySelectorAll(){return [];}};
const context=vm.createContext({document,URL,console,setInterval:()=>0,fetch:()=>new Promise(()=>{}),fixture:FIXTURE});
vm.runInContext(SCRIPT,context);
vm.runInContext("snapshot=fixture;selected='h';renderTree();renderDetail();",context);
function visible(e){return e.tag==='details'?'':e.text+e.children.map(visible).join('');}
function links(e){return (e.tag==='a'?[e.href]:[]).concat(...e.children.map(links));}
assert(elements.get('evidence').textContent.includes('<script>Paper title</script>'));
assert(links(elements.get('evidence')).includes('https://example.com/paper'));
assert(elements.get('novelty').textContent.includes('Uncertain novelty'));
assert(elements.get('experiment').textContent.includes('Accuracy'));
assert(elements.get('experiment').textContent.includes('ViT-tiny'));
const evaluations=visible(elements.get('evaluations'));
assert(evaluations.includes('Chairman rationale'));
assert(evaluations.includes('Selected peer rationale'));
assert(evaluations.includes('Shared blind spot'));
assert(!evaluations.includes('Other candidate rationale'));
assert(!elements.get('metadata').textContent.includes('HIDDEN_IDENTITY'));
assert(!elements.get('metadata').textContent.includes('HIDDEN_AUTHOR'));
assert(elements.get('add-branch').disabled);
vm.runInContext("fixture.notes=[{node_id:'h',kind:'experiment',title:'실험 설계',content:'아직 실행하지 않음',created_at:'2026-10-24'}];fixture.nodes[1].metadata.korean_display={hypothesis:'한글 아이디어',experiment:{metric:'한글 지표'}};renderDetail();",context);
assert(elements.get('idea').textContent.includes('한글 아이디어'));
assert(elements.get('experiment').textContent.includes('한글 지표'));
assert(elements.get('notes').textContent.includes('아직 실행하지 않음'));
vm.runInContext("transcript=[{run_id:'r',round:1,phase:'generation',participant:'Codex',direction:'response',content:'{\\\"hypothesis\\\":\\\"실제 응답\\\"}',source:'response.txt'}];document.getElementById('trace-phase').value='all';renderConversation();",context);
assert(elements.get('conversation').textContent.includes('실제 응답'));
assert(elements.get('conversation').textContent.includes('Codex'));
vm.runInContext("renderProviders({providers:[{name:'GPT',connection:'connected',windows:[{minutes:300,used_percent:0}],checked_at:'2026-10-24'},{name:'Claude',connection:'authenticated',usage_state:'rate_limited',windows:[],checked_at:'2026-10-24'}]});",context);
assert(elements.get('provider-status').textContent.includes('0% 사용'));
assert(elements.get('provider-status').textContent.includes('사용량 조회 제한'));
vm.runInContext("fixture.nodes[1].status='active';renderTree();",context);
function all(e){return [e].concat(...e.children.map(all));}
assert(all(elements.get('tree')).some(e=>(e.className||'').includes('is-active')));
vm.runInContext("fixture.nodes[1].status='discarded';selected='root';renderTree();",context);
const archived=all(elements.get('tree')).find(e=>e.className==='discarded-group');
assert(archived);
assert(all(archived).some(e=>(e.className||'').includes('is-discarded')));
assert(!archived.open);
vm.runInContext("projectOpen.set('root',false);renderTree();",context);
assert(!elements.get('tree').textContent.includes('Hypothesis'));
vm.runInContext("computeState={profiles:[{id:'local',name:'Mac',kind:'local'}],assignments:{},inventories:{}};document.getElementById('settings-project').value='root';renderTargets('local');renderTarget();document.getElementById('settings-tab-ssh').onclick();",context);
assert(elements.get('settings-panel-execution').hidden);
assert(!elements.get('settings-panel-ssh').hidden);
assert.strictEqual(elements.get('ssh-host').value,'');
assert.strictEqual(elements.get('compute-target').value,'__new__');
vm.runInContext("setSettingsTab('execution');",context);
assert(!elements.get('settings-panel-execution').hidden);
assert(elements.get('settings-panel-ssh').hidden);
assert.strictEqual(elements.get('compute-target').value,'local');
vm.runInContext("computeState.inventories.local={connected:true,checked_at:'2026-10-24',devices:[{id:'cpu',name:'CPU',kind:'cpu'},{id:'metal:0',name:'Apple M4',kind:'metal'}]};document.getElementById('new-project-target').value='local';renderNewProjectDevices(['metal:0']);",context);
assert(elements.get('new-project-devices').textContent.includes('Apple M4'));
assert(all(elements.get('new-project-devices')).some(e=>e.value==='metal:0'&&e.checked));
vm.runInContext("fixture.projects=[{id:'root',title:'Trashed Project',deleted_at:'2026-10-24'}];for(const node of fixture.nodes)node.project_id='root';renderTree();renderDetail();renderProjectTrash();",context);
assert(!elements.get('tree').textContent.includes('Hypothesis'));
assert(elements.get('detail').hidden);
assert(!elements.get('open-project-trash').hidden);
assert(elements.get('project-trash-list').textContent.includes('Trashed Project'));
assert(elements.get('project-trash-list').textContent.includes('복원'));
console.log('Viewer rendering behavior: PASS');
""".replace('FIXTURE', json.dumps(fixture)).replace('SCRIPT', json.dumps(script))
        result = subprocess.run([node, '-'], input=harness, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main(verbosity=2)
