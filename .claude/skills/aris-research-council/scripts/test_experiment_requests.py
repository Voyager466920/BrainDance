"""Human request routing and actual CPU transport; all model answers are fixtures."""
import json
from pathlib import Path
import time
import unittest
from unittest.mock import patch

import test_native_pipeline as fixtures
from experiment_requests import add,parse,activate
from research_tasks import listing,stage
from native_pipeline import Host,install,SKILLS


class ExperimentRequestTests(unittest.TestCase):
    def setUp(self):
        self.base=fixtures.NativePipelineTests();self.base.setUp();self.addCleanup(self.base.doCleanups)
        self.server=self.base.server;self.control=self.server.autopilot;self.pid=self.base.node['project_id']
        self.item=self.control.get(self.base.session['id']);self.store=self.server.store
    def add(self,text='OFFLINE compare baseline and candidate',key='experiment-request-offline-0001'):
        return add(self.control,self.pid,text,key)
    def release_original_job(self):
        with self.store._connect() as c:c.execute("UPDATE research_jobs SET state='completed',phase='native-completed' WHERE id=?",(self.base.job['id'],))
        self.server.research.active_id=None
    def test_explicit_command_parsing_does_not_interpret_questions_as_requests(self):
        self.assertEqual(parse('새 실험: 비교 A\n비교 B'),'비교 A\n비교 B')
        self.assertEqual(parse('실험 추가： 비교'),'비교');self.assertEqual(parse('new experiment: compare'),'compare')
        self.assertIsNone(parse('새 실험을 추가할 수 있나?'));self.assertEqual(parse('새 실험:'),'')
    def test_request_is_durable_unverified_and_idempotent_with_unchanged_limits(self):
        before=self.control.get(self.item['id']);ledger=Path(before['config']['session_budget']).read_bytes()
        first=self.add();second=self.add();self.assertEqual(first,second)
        tasks=listing(self.store,self.item['id']);self.assertEqual(len(tasks),1);self.assertEqual(tasks[0]['state'],'queued')
        node=self.store.get_node(first['node_id']);self.assertTrue(node['metadata']['human_requested']);self.assertEqual(node['metadata']['novelty_status'],'unverified')
        self.assertNotIn('research_ratings',node['metadata']);self.assertEqual(self.control.get(self.item['id']),before)
        self.assertEqual(Path(before['config']['session_budget']).read_bytes(),ledger)
        with self.assertRaisesRegex(ValueError,'내용'):self.add('changed')
        self.assertEqual(len(listing(self.store,self.item['id'])),1)
    def test_stopped_session_only_saves_request_and_explicit_continuation_keeps_it(self):
        self.control.control(dict(project_id=self.pid,action='stop'));result=self.add()
        self.assertEqual(result['session_status'],'stopped');self.assertEqual(self.control.get(self.item['id'])['status'],'stopped')
        with patch.object(self.server.research,'start',side_effect=AssertionError('Must not launch on add')):self.add()
        # Offline _execute does not run the real worker's cancellation cleanup.
        with self.store._connect() as c:c.execute("UPDATE research_jobs SET state='cancelled' WHERE project_id=?",(self.pid,))
        result=self.control.control(dict(project_id=self.pid,session_id=self.item['id'],action='resume',duration_seconds=60))
        self.assertEqual(result['session']['id'],self.item['id']);self.assertEqual(listing(self.store,self.item['id'])[0]['state'],'queued')
    def test_request_without_session_waits_and_binds_on_first_authorized_start(self):
        self.control.control(dict(project_id=self.pid,action='stop'))
        with self.store._connect() as c:c.execute('DELETE FROM automatic_sessions WHERE project_id=?',(self.pid,))
        result=self.add();self.assertIsNone(result['session_status'])
        with self.store._connect() as c:self.assertIsNone(c.execute('SELECT session_id FROM experiment_requests').fetchone()[0])
        item=self.control.control(dict(project_id=self.pid,action='start',execution_policy='until_deadline',duration_seconds=60))['session']
        activate(self.control,item);self.assertEqual(len(listing(self.store,item['id'])),1)
        exported=self.store.export_json();self.assertEqual(exported['experiment_requests'][0]['node_id'],result['node_id'])
    def test_shared_chat_acknowledges_once_without_llm_or_implicit_resume(self):
        self.control.control(dict(project_id=self.pid,action='stop'))
        payload=dict(node_id=self.base.node['id'],content='새 실험: OFFLINE comparison',mode='auto',request_id='chat-experiment-offline-0001')
        with patch('council.codex_call',side_effect=AssertionError('No model for request registration')):
            first=self.server.chat.send(payload);second=self.server.chat.send(payload)
        self.assertEqual(first['id'],second['id']);self.assertEqual(first['state'],'completed')
        self.assertEqual(first['metadata']['reply_model_calls'],0);self.assertIn('요청만 저장',first['content'])
        self.assertEqual(len(listing(self.store,self.item['id'])),1)
        with self.assertRaisesRegex(ValueError,'형식'):self.server.chat.send({**payload,'request_id':'empty-experiment-request-0001','content':'새 실험:'})
    def test_running_study_is_not_interrupted_and_requested_study_uses_original_runner(self):
        result=self.add();self.control.native_tick(self.control.get(self.item['id']))
        task=listing(self.store,self.item['id'])[0];self.assertEqual(task['state'],'queued')
        self.assertEqual(self.server.research.get(self.base.job['id'])['id'],self.base.job['id'])
        self.release_original_job();self.control.native_tick(self.control.get(self.item['id']))
        task=listing(self.store,self.item['id'])[0];self.assertEqual(task['state'],'running')
        job=self.server.research.get(task['job_id']);self.assertEqual(job['config']['task_role'],'study')
        self.assertEqual(job['config']['hypothesis_task_id'],result['id']);self.assertEqual(job['config']['session_budget'],self.item['config']['session_budget'])
        self.assertEqual(job['config']['project_session']['id'],self.base.config['project_session']['id'])
        work=Path(job['config']['native_workspace']);install(job['config'])
        from test_official_review import discovery_fixture
        discovery_fixture(job['config'])
        rows=[]
        for i,skill in enumerate(SKILLS):rows.extend([dict(type='assistant',message=dict(content=[dict(type='tool_use',id=str(i),name='Skill',input=dict(skill='aris-official:'+skill))])),dict(type='user',message=dict(content=[dict(type='tool_result',tool_use_id=str(i),content='OFFLINE request fixture')]))])
        (Path(job['run_dir'])/'native.stdout.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows))
        (work/'pilot.py').write_text('import os,json\nfrom pathlib import Path\ndef self_test():\n assert 2+2==4\ndef run_experiment():\n Path(os.environ["BRAINDANCE_METRICS_PATH"]).write_text(json.dumps({"baseline":{"metric":1},"candidate":{"metric":2}}))\n')
        with patch('native_pipeline.council.codex_call',side_effect=self.base.fake_review):receipt=Host(job['config']).execute('experiment',dict(source='pilot.py',title='OFFLINE requested CPU fixture',interpreter='builtin',timeout_seconds=3,metric='metric'))
        end=time.monotonic()+8
        while time.monotonic()<end:
            run=self.server.experiments.run_info(receipt['run_id'])
            if run['state'] not in {'queued','running'}:break
            time.sleep(.03)
        self.assertEqual(run['state'],'succeeded')
        self.assertEqual(run['result']['metrics']['candidate']['metric'],2)
    def test_discovery_staging_does_not_treat_human_request_as_verified_discovery(self):
        requested=self.add();job={**self.base.job,'config':{**self.base.job['config'],'task_role':'discovery','native_cycle':0}}
        node=self.store.add_node(self.base.node['id'],'OFFLINE verified discovery',metadata=dict(scout_cycle=0,novelty_recheck={'novelty_status':'unverified'},rating_basis='OFFLINE',research_ratings=dict(potential=50,novelty_provisional=50,feasibility=50,falsifiability=50)))
        first=stage(self.control,job,self.item,[node['id']]);second=stage(self.control,job,self.item,[node['id']])
        self.assertEqual(len(first),1);self.assertEqual(first,second);self.assertNotEqual(first[0]['id'],requested['id'])
        self.assertEqual(len(listing(self.store,self.item['id'])),2)

    def test_held_request_is_retained_but_not_dispatched(self):
        result=self.add();self.store.update_node(result['node_id'],status='held')
        self.release_original_job()
        with patch.object(self.server.research,'start',side_effect=AssertionError('Held request must not run')):self.control.native_tick(self.control.get(self.item['id']))
        self.assertEqual(listing(self.store,self.item['id'])[0]['state'],'queued')

    def test_http_requires_exact_fields_and_trash_blocks_new_requests(self):
        client=self.base.fixture.client
        result=client.request('/api/control/experiment-request',dict(project_id=self.pid,content='OFFLINE API request',request_id='api-experiment-offline-0001'))
        self.assertEqual(self.store.get_node(result['node_id'])['project_id'],self.pid)
        from terminal import ClientError
        with self.assertRaises(ClientError):client.request('/api/control/experiment-request',dict(project_id=self.pid,content='bad',request_id='api-experiment-offline-0002',duration_seconds=999999))
        self.store.set_project_deleted(self.pid,True)
        with self.assertRaisesRegex(ValueError,'휴지통'):self.add(key='trash-experiment-offline-0001')
