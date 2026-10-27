"""Native ARIS transport/authorization checks. Fixtures never claim model research."""
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import council
from native_pipeline import Host,action,install,SKILLS
import test_terminal as fixtures
import steering
from terminal import ClientError


class NativePipelineTests(unittest.TestCase):
    def setUp(self):
        self.loop=patch('autopilot.Autopilot._loop',return_value=None);self.loop.start();self.addCleanup(self.loop.stop)
        self.fixture=fixtures.TerminalTests('test_source_command_json_does_not_emit_logo_or_color');self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.server=self.fixture.server;self.node=self.fixture.client.root(self.fixture.project)
        self.aris=Path(self.fixture.temp.name)/'upstream'
        for name in SKILLS:
            p=self.aris/'skills'/name/'SKILL.md';p.parent.mkdir(parents=True);p.write_text('OFFLINE upstream fixture '+name)
        (self.aris/'tools').mkdir()
        self.server.research.availability=lambda:dict(available=True,missing=[],aris_repo=str(self.aris))
        self.server.research._execute=lambda record:None
        self.session=self.server.autopilot.control(dict(project_id=self.node['project_id'],action='start',max_cycles=1,max_model_calls=80,token_budget=2000000))['session']
        self.server.autopilot.tick(self.session)
        session=self.server.autopilot.get(self.session['id']);self.job=self.server.research.get(session['progress']['job_id'])
        self.config=self.job['config'];install(self.config);self.host=Host(self.config)
        rows=[]
        for i,name in enumerate(SKILLS):
            rows.extend([dict(type='assistant',message=dict(content=[dict(type='tool_use',id=str(i),name='Skill',input=dict(skill='aris-official:'+name))])),dict(type='user',message=dict(content=[dict(type='tool_result',tool_use_id=str(i),content='OFFLINE receipt fixture')]))])
        (Path(self.job['run_dir'])/'native.stdout.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
        self.work=Path(self.config['native_workspace'])
    def call(self,kind,**kw):return action(self.server,dict(job_id=self.job['id'],action=kind,**kw))
    def fake_review(self,folder,prompt,*args):
        folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
        council.dump(folder/'usage.json',dict(fixture=True))
        council.dump(folder/'response.txt',dict(verdict='pass',reasons=['OFFLINE transport fixture']))
        # response.txt is plain JSON in the real MCP receipt too.
        return dict(verdict='pass',reasons=[])
    def experiment(self):
        (self.work/'advice-ideas.json').write_text('{"fixture":true}')
        (self.work/'experiment.py').write_text('import os,json\nfrom pathlib import Path\ndef self_test():\n assert 2+2==4\ndef run_experiment():\n Path(os.environ["BRAINDANCE_METRICS_PATH"]).write_text(json.dumps({"baseline":{"sum":2},"candidate":{"sum":3}}))\n')
        with patch('native_pipeline.council.codex_call',side_effect=self.fake_review):
            return self.host.execute('experiment',dict(source='experiment.py',title='OFFLINE native transport fixture',interpreter='builtin',timeout_seconds=3,metric='sum',direction='maximize'))
    def wait_run(self,run_id):
        deadline=time.monotonic()+8
        while time.monotonic()<deadline:
            run=self.call('receipt',run_id=run_id)
            if run['state'] not in {'queued','running'}:return run
            time.sleep(.05)
        self.fail('actual disposable CPU fixture did not finish')
    def test_new_sessions_use_native_driver_and_preserve_official_skill_bytes(self):
        self.assertEqual(self.session['config']['pipeline'],'aris-native')
        self.assertEqual(self.config['task'],'native')
        for name in SKILLS:self.assertEqual((self.work/'.aris-official/skills'/name/'SKILL.md').read_bytes(),(self.aris/'skills'/name/'SKILL.md').read_bytes())
        self.assertEqual(install(self.config)[0],self.work)
        (self.aris/'skills/research-pipeline/SKILL.md').write_text('changed upstream')
        with self.assertRaisesRegex(ValueError,'변경'):install(self.config)
    def test_actual_execution_uses_existing_broker_limits_and_shared_conversation(self):
        steering.record(self.server.store,self.node['id'],'preserve existing baseline','next')
        context=self.host.execute('context',{})
        self.assertIn('preserve existing baseline',json.dumps(context))
        run=self.experiment();receipt=self.wait_run(run['run_id'])
        self.assertEqual(receipt['state'],'succeeded')
        self.assertEqual(receipt['result']['analysis']['status'],'compared')
        self.assertIn('passed',receipt['stdout_tail'])
        with self.assertRaisesRegex(ClientError,'횟수'):self.experiment()
        self.assertEqual(len(self.call('context')['completed_runs']),1)
    def test_paused_session_and_direction_changes_cannot_dispatch_stale_code(self):
        self.server.autopilot.control(dict(project_id=self.node['project_id'],action='pause'))
        with self.assertRaisesRegex(ClientError,'중지'):self.host.execute('context',{})
        self.server.autopilot.save(self.server.autopilot.get(self.session['id']),'running')
        def changed(folder,prompt,*args):
            result=self.fake_review(folder,prompt,*args)
            steering.record(self.server.store,self.node['id'],'new comparison','next')
            return result
        with patch('native_pipeline.council.codex_call',side_effect=changed):
            (self.work/'advice-ideas.json').write_text('{}')
            (self.work/'code.py').write_text('def self_test():\n assert True\ndef run_experiment():\n pass\n')
            with self.assertRaisesRegex(ClientError,'새 사용자'):self.host.execute('experiment',dict(source='code.py',title='stale',timeout_seconds=1))
        self.assertEqual(self.call('context')['runs_started'],0)
    def test_completion_requires_real_results_latest_council_and_original_reviewer(self):
        report=self.work/'NARRATIVE_REPORT.md';report.write_text('OFFLINE transport validation')
        with self.assertRaisesRegex(ValueError,'실제 실험'):self.call('finish',report=str(report))
        run=self.experiment();self.wait_run(run['run_id'])
        (self.work/'advice-results.json').write_text('{"run_ids":[]}')
        with self.assertRaisesRegex(ValueError,'최신 실험'):self.call('finish',report=str(report))
        council.dump(self.work/'advice-results.json',dict(run_ids=[run['run_id']]))
        with self.assertRaisesRegex(ValueError,'Reviewer'):self.call('finish',report=str(report))
        reviewer=Path(self.job['run_dir'])/'native-reviewer/offline';reviewer.mkdir(parents=True);(reviewer/'usage.json').write_text('{"fixture":true}');council.dump(self.work/'reviewer-latest.json',dict(receipt=str(reviewer/'usage.json'),run_ids=[run['run_id']]))
        receipt=self.call('finish',report=str(report))
        self.assertEqual(receipt['run_ids'],[run['run_id']])
        self.assertEqual(json.loads((self.work/'native-completion.json').read_text())['job_id'],self.job['id'])
    def test_quick_native_pause_resume_retains_a_still_running_job(self):
        self.server.autopilot.control(dict(project_id=self.node['project_id'],action='pause'))
        resumed=self.server.autopilot.control(dict(project_id=self.node['project_id'],action='resume'))['session']
        self.assertEqual(resumed['progress']['job_id'],self.job['id'])
        self.assertEqual(resumed['progress']['phase'],'native')

    def test_explicit_legacy_resume_migrates_without_resetting_usage_or_history(self):
        from session_budget import update
        ledger=Path(self.session['config']['session_budget']);update(ledger,'reserve',key='retained',calls=1,estimate=123)
        before=ledger.read_bytes()
        old=self.server.autopilot.get(self.session['id']);old['config']['pipeline']='discovery-to-results'
        old['progress'].update(phase='analysis',cycles=1)
        with self.server.store._connect() as conn:
            conn.execute("UPDATE research_jobs SET state='interrupted' WHERE id=?",(self.job['id'],))
            conn.execute('UPDATE automatic_sessions SET config=?,progress=?,status=? WHERE id=?',(json.dumps(old['config']),json.dumps(old['progress']),'paused',old['id']))
        result=self.server.autopilot.control(dict(project_id=self.node['project_id'],action='resume'))['session']
        self.assertEqual(result['config']['pipeline'],'aris-native')
        self.assertEqual(result['config']['previous_pipeline'],'discovery-to-results')
        self.assertEqual(result['config']['legacy_progress']['cycles'],1)
        self.assertEqual(result['id'],old['id']);self.assertEqual(ledger.read_bytes(),before)
        self.assertEqual(result['config']['resource_signature'],old['config']['resource_signature'])
        self.assertIsNone(result['progress']['job_id'])

    def test_nested_native_skills_cannot_be_silently_replaced_by_reading_documents(self):
        (Path(self.job['run_dir'])/'native.stdout.jsonl').write_text('')
        with self.assertRaisesRegex(ValueError,'실제 호출'):self.host.execute('council',dict(stage='ideas'))

    def test_host_rejects_foreign_paths_and_arbitrary_helper_execution(self):
        for name in ['../tree.sqlite3','/etc/passwd','.aris-official/skills/research-pipeline/SKILL.md']:
            with self.assertRaises(ValueError):self.host.path(name)
        with self.assertRaises(ValueError):self.host.execute('helper',dict(name='install_aris.sh',args=[]))
