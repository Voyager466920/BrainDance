"""Native ARIS transport/authorization checks. Fixtures never claim model research."""
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import council
from native_pipeline import Host,action,install,SKILLS,review_directory
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

    def test_review_receipt_cannot_be_reused_for_changed_runtime_arguments_or_source(self):
        from lab_worker import check_code
        context=self.host.execute('context',{})
        spec=dict(node_id=self.node['id'],code=check_code('def self_test():\n assert True\ndef run_experiment():\n pass\n'),title='OFFLINE receipt binding',interpreter='builtin',timeout_seconds=30)
        folder=review_directory(self.job['run_dir'],spec,context['revision'],context['resource_signature'])
        self.fake_review(folder,'OFFLINE fixture')
        for change in [dict(timeout_seconds=31),dict(args=['changed']),dict(code=spec['code']+'\n# changed source')]:
            with self.assertRaisesRegex(ValueError,'영수증'):
                self.call('experiment',payload={**spec,**change},review_receipt=str(folder/'usage.json'),direction_revision=context['revision'])
        self.assertEqual(self.call('context')['runs_started'],0)

    def test_failed_execution_is_debugged_without_consuming_the_measured_experiment_quota(self):
        (self.work/'advice-ideas.json').write_text('{}')
        (self.work/'broken.py').write_text('def self_test():\n assert True\ndef run_experiment():\n raise ModuleNotFoundError("OFFLINE missing dependency fixture")\n')
        with patch('native_pipeline.council.codex_call',side_effect=self.fake_review):
            first=self.host.execute('experiment',dict(source='broken.py',title='OFFLINE failed first attempt',timeout_seconds=3))
        self.assertEqual(self.wait_run(first['run_id'])['state'],'failed')
        context=self.call('context');self.assertEqual(context['attempts_started'],1);self.assertEqual(context['completed_experiments'],0)
        repaired=self.experiment();self.assertEqual(self.wait_run(repaired['run_id'])['state'],'succeeded')
        context=self.call('context');self.assertEqual(context['attempts_started'],2);self.assertEqual(context['completed_experiments'],1)

    def test_failed_worker_recovers_same_session_with_backoff_and_retained_budget(self):
        with self.server.store._connect() as conn:conn.execute("UPDATE research_jobs SET state='failed',message='OFFLINE temporary worker error' WHERE id=?",(self.job['id'],))
        self.server.research.active_id=None
        ledger=Path(self.config['session_budget']);before=ledger.read_bytes()
        item=self.server.autopilot.get(self.session['id']);self.server.autopilot.native_tick(item)
        current=self.server.autopilot.get(item['id']);self.assertEqual(current['status'],'running');self.assertEqual(current['progress']['phase'],'recovery')
        self.assertGreater(current['progress']['recovery_after'],time.time());self.assertEqual(ledger.read_bytes(),before)
        self.server.autopilot.save(current,recovery_after=0);self.server.autopilot.native_tick(current)
        current=self.server.autopilot.get(item['id']);retry=self.server.research.get(current['progress']['job_id'])
        self.assertNotEqual(retry['id'],self.job['id']);self.assertEqual(retry['config']['auto_session_id'],self.session['id'])
        self.assertEqual(retry['config']['native_workspace'],self.config['native_workspace']);self.assertEqual(ledger.read_bytes(),before)

    def test_automatic_recovery_does_not_expand_exhausted_model_limits(self):
        from session_budget import update
        update(self.config['session_budget'],'reserve',key='OFFLINE used allowance',calls=80,estimate=2000000)
        with self.server.store._connect() as conn:conn.execute("UPDATE research_jobs SET state='failed',message='OFFLINE worker error' WHERE id=?",(self.job['id'],))
        with self.assertRaisesRegex(RuntimeError,'소진'):self.server.autopilot.native_tick(self.server.autopilot.get(self.session['id']))

    def test_identical_blocked_review_reuses_exact_receipt_without_another_model_call(self):
        (self.work/'advice-ideas.json').write_text('{}')
        (self.work/'cached.py').write_text('def self_test():\n assert True\ndef run_experiment():\n pass\n')
        def blocked(folder,prompt,*args):
            folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
            result=dict(verdict='block',reasons=['OFFLINE correctness blocker'])
            council.dump(folder/'usage.json',dict(fixture=True));council.dump(folder/'response.txt',result)
            council.dump(folder/'request.json',dict(params=dict(arguments=dict(prompt=prompt))))
            return result
        spec=dict(source='cached.py',title='OFFLINE cached review',timeout_seconds=3)
        with patch('native_pipeline.council.codex_call',side_effect=blocked):self.assertEqual(self.host.execute('experiment',dict(spec))['state'],'review_blocked')
        ledger=Path(self.config['session_budget']);before=ledger.read_bytes()
        with patch('council.subprocess.Popen',side_effect=AssertionError('Identical completed review must not dispatch another provider call')):
            self.assertEqual(self.host.execute('experiment',dict(spec))['state'],'review_blocked')
        self.assertEqual(ledger.read_bytes(),before)
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
    def test_successful_skill_receipts_are_reused_only_in_the_same_automatic_session(self):
        from native_pipeline import session_skill_receipts
        resumed={**self.config,'id':'resumed-job'}
        invoked,sources,_=session_skill_receipts(resumed)
        self.assertEqual(invoked,set(SKILLS));self.assertTrue(sources)
        unrelated={**resumed,'auto_session_id':'different-authorization'}
        self.assertEqual(session_skill_receipts(unrelated)[0],set())

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
