"""Deadline-only accounting, continuation and real CPU cancellation; no paid models."""
import json
from pathlib import Path
import time
import unittest
from unittest.mock import patch

from council import Budget
from session_budget import update,DeadlineExpired
from native_pipeline import Host
import test_native_pipeline as fixtures


class DeadlineTests(unittest.TestCase):
    call=fixtures.NativePipelineTests.call
    wait_run=fixtures.NativePipelineTests.wait_run
    fake_review=fixtures.NativePipelineTests.fake_review

    def setUp(self):
        fixtures.NativePipelineTests.setUp(self)

    def authorize(self,seconds=60):
        return self.server.autopilot.control(dict(project_id=self.node['project_id'],action='time_only',duration_seconds=seconds))

    def test_counts_tokens_and_stage_presets_are_accounting_only_until_deadline(self):
        self.authorize();ledger=Path(self.config['session_budget'])
        budget=Budget(dict(max_model_calls=1,token_budget=1,session_budget=str(ledger)),self.work/'deadline-budget.json')
        budget.reserve(1000,10**12)
        record=json.loads(ledger.read_text());self.assertEqual(record['calls'],1000)
        self.assertIsNone(record['max_calls']);self.assertIsNone(record['token_budget'])
        with patch('session_budget.time.time',return_value=record['deadline_epoch']+1):
            with self.assertRaises(DeadlineExpired):budget.reserve(1,1)
            update(ledger,'record',key='late actual receipt',tokens=123)
        self.assertEqual(json.loads(ledger.read_text())['observed']['late actual receipt'],123)

    def test_completed_cycles_continue_without_terminating_project_or_reusing_old_completion(self):
        state=self.authorize();item=state['session'];ledger=Path(self.config['session_budget']);before=ledger.read_bytes()
        for cycle in range(2):
            current=self.server.autopilot.get(item['id']);job_id=current['progress']['job_id']
            with self.server.store._connect() as conn:conn.execute("UPDATE research_jobs SET state='completed',phase='native-completed' WHERE id=?",(job_id,))
            self.server.research.active_id=None;self.server.autopilot.native_tick(current)
            current=self.server.autopilot.get(item['id']);self.assertEqual(current['status'],'running')
            self.assertEqual(current['progress']['cycles_completed'],cycle+1)
            self.server.autopilot.native_tick(current)
            current=self.server.autopilot.get(item['id']);job=self.server.research.get(current['progress']['job_id'])
            self.assertEqual(job['config']['native_cycle'],cycle+1)
            self.assertEqual(job['config']['native_workspace'],self.config['native_workspace'])
        self.assertEqual(ledger.read_bytes(),before)

    def test_until_deadline_context_has_no_experiment_count_cap(self):
        self.authorize()
        context=self.host.execute('context',{})
        self.assertIsNone(context['max_runs']);self.assertEqual(context['execution_policy'],'until_deadline')
        self.assertGreater(context['execution_budget']['max_timeout_seconds'],0)

    def test_deadline_cancels_a_running_cpu_process_and_blocks_further_dispatch(self):
        self.authorize(10)
        (self.work/'advice-ideas.json').write_text('{}')
        (self.work/'long.py').write_text('import time\ndef self_test():\n assert True\ndef run_experiment():\n print("DEADLINE_CPU_STARTED",flush=True)\n time.sleep(30)\n')
        with patch('native_pipeline.council.codex_call',side_effect=self.fake_review):
            started=self.host.execute('experiment',dict(source='long.py',title='OFFLINE deadline cancellation',timeout_seconds=8))
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            if 'DEADLINE_CPU_STARTED' in self.server.experiments.run_info(started['run_id'])['stdout_tail']:break
            time.sleep(.02)
        self.server.autopilot.control(dict(project_id=self.node['project_id'],action='deadline',duration_seconds=1))
        time.sleep(1.05);self.server.autopilot.tick(self.server.autopilot.get(self.session['id']))
        limit=time.monotonic()+4
        while time.monotonic()<limit:
            actual=self.server.experiments.run_info(started['run_id'])
            if actual['state'] not in {'queued','running'}:break
            time.sleep(.03)
        self.assertIn(actual['state'],{'cancelled','timed_out'})
        self.assertEqual(self.server.autopilot.get(self.session['id'])['status'],'completed')
        with self.assertRaises(DeadlineExpired):update(self.config['session_budget'],'reserve',calls=1,estimate=1,key='late')

    def test_cli_default_start_and_time_extension_preserve_real_usage(self):
        import terminal
        self.server.autopilot.control(dict(project_id=self.node['project_id'],action='stop'))
        project=self.fixture.project
        args=terminal.parser().parse_args(['auto','start','--hours','8'])
        state=terminal.dispatch(self.fixture.client,args,project)
        self.assertEqual(state['session']['config']['execution_policy'],'until_deadline')
        self.assertIsNone(state['usage']['max_calls']);self.assertIsNone(state['usage']['token_budget'])
        ledger=state['session']['config']['session_budget']
        update(ledger,'reserve',calls=321,estimate=10**10,key='OFFLINE retained receipt')
        changed=terminal.dispatch(self.fixture.client,terminal.parser().parse_args(['limits','--hours','9']),project)
        self.assertEqual(changed['session']['id'],state['session']['id'])
        self.assertEqual(changed['usage']['calls'],321);self.assertEqual(changed['usage']['charged_tokens'],10**10)
        self.assertGreater(changed['usage']['deadline_epoch'],state['usage']['deadline_epoch'])

    def test_restart_keeps_original_deadline_and_expired_literature_cannot_dispatch(self):
        from autopilot import Autopilot
        state=self.authorize();before=state['usage']['deadline_epoch']
        restarted=Autopilot(self.server.store,self.server.research,self.server.experiments,autostart=False)
        self.addCleanup(restarted.close)
        self.assertEqual(restarted.get(self.session['id'])['status'],'running')
        self.assertEqual(restarted.state(self.node['project_id'])['usage']['deadline_epoch'],before)
        self.server.research.active_id=None
        with self.server.store._connect() as conn:
            conn.execute("INSERT INTO conversation_actions VALUES(?,?,?,?,?,?,?,?,?)",('OFFLINE-after-clock',self.node['project_id'],self.node['id'],'literature','pending','OFFLINE find papers',None,'{}','2026-01-01'))
        with patch('session_budget.time.time',return_value=before+1),patch.object(self.server.research,'start') as dispatch:
            restarted._conversation_requests();dispatch.assert_not_called()
        with self.server.store._connect() as conn:row=conn.execute("SELECT state,receipt FROM conversation_actions WHERE id='OFFLINE-after-clock'").fetchone()
        self.assertEqual(row['state'],'blocked');self.assertIn('종료 시각',json.loads(row['receipt'])['error'])

    def test_human_per_experiment_time_applies_without_new_count_caps(self):
        self.authorize(60)
        changed=self.server.autopilot.control(dict(project_id=self.node['project_id'],action='deadline',duration_seconds=60,experiment_timeout_seconds=2))
        context=self.call('context');self.assertEqual(context['execution_budget']['max_timeout_seconds'],2)
        self.assertEqual(context['execution_budget']['recommended_timeout_seconds'],2);self.assertIsNone(context['max_runs'])
        self.assertIsNone(changed['usage']['max_calls'])
        with self.assertRaises(ValueError):self.server.autopilot.control(dict(project_id=self.node['project_id'],action='deadline',duration_seconds=60,experiment_timeout_seconds=-1))
        self.server.autopilot.control(dict(project_id=self.node['project_id'],action='deadline',duration_seconds=60,experiment_timeout_seconds=None))
        self.assertGreater(self.call('context')['execution_budget']['max_timeout_seconds'],2)

    def test_per_experiment_limit_terminates_real_cpu_work_before_project_deadline(self):
        self.authorize(60)
        self.server.autopilot.control(dict(project_id=self.node['project_id'],action='deadline',duration_seconds=60,experiment_timeout_seconds=2))
        (self.work/'advice-ideas.json').write_text('{}')
        (self.work/'per-run.py').write_text('import time\ndef self_test():\n assert True\ndef run_experiment():\n time.sleep(15)\n')
        with patch('native_pipeline.council.codex_call',side_effect=self.fake_review):
            run=self.host.execute('experiment',dict(source='per-run.py',title='OFFLINE per-experiment timeout',timeout_seconds=30))
        actual=self.wait_run(run['run_id'])
        self.assertEqual(self.server.experiments.run_info(run['run_id'])['timeout_seconds'],2);self.assertEqual(actual['state'],'timed_out')
        self.assertEqual(self.server.autopilot.state(self.node['project_id'])['session']['status'],'running')
