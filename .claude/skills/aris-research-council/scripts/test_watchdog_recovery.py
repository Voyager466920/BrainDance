"""Offline repair control tests; no provider, SSH or real research measurements."""
import json
from pathlib import Path
import time
import unittest
from unittest.mock import patch
import council
import test_terminal as fixtures
from watchdog_recovery import Recovery
from tree_store import now
from literature_inputs import normalize


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.TerminalTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.s=self.f.server;self.s.recovery.close();self.s.recovery=Recovery(self.s,autostart=False)
        self.session=self.s.autopilot.control(dict(project_id=self.f.project['id'],action='start',execution_policy='until_deadline',duration_seconds=3600))['session']
        self.folder=self.f.db.parent/'council-runs/OFFLINE-failed';self.folder.mkdir()
        self.work=self.f.db.parent/'workspace';self.work.mkdir()
        self.config=dict(auto_session_id=self.session['id'],native_workspace=str(self.work),session_budget=self.session['config']['session_budget'],aris_repo='/OFFLINE')
        self.trace=self.folder/'native.stdout.jsonl'
        self.trace.write_text(json.dumps(dict(message=dict(content=[dict(type='tool_use',id='t',name='mcp__codex__exploration_council')])) )+'\n'+json.dumps(dict(message=dict(content=[dict(type='tool_result',tool_use_id='t',is_error=True,content='candidate_papers.json must be an array')])) )+'\n')
        with self.s.store._connect() as c:c.execute('INSERT INTO research_jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',('OFFLINE-failed',self.f.project['id'],self.f.project['id'],'OFFLINE','failed','verification','missing receipt','lite',json.dumps(self.config),str(self.folder),now(),now(),now(),'missing receipt'))
    def request(self):return self.s.recovery.request(dict(session_id=self.session['id'],kind='repeated-missing-receipt'))
    def row(self,rid):
        with self.s.store._connect() as c:return dict(c.execute('SELECT * FROM watchdog_repairs WHERE id=?',(rid,)).fetchone())
    def model(self,folder,prompt,settings,budget,repo):
        self.assertIn('candidate_papers.json must be an array',prompt)
        self.assertEqual(settings['session_budget'],self.config['session_budget'])
        budget.reserve(1,2000);budget.record(dict(total_tokens=1000,stage_path=str(folder)))
        Path(folder).mkdir(parents=True);council.dump(Path(folder)/'usage.json',dict(fixture=True))
        return dict(action='resume_native',root_cause='OFFLINE schema mismatch',repair_instructions=['Use normalized explicit identifiers'],checks=['Retry the actual exploration tool'])
    def test_diagnosis_retains_same_limits_and_requires_actual_progress(self):
        before=self.s.autopilot.get(self.session['id']);r=self.request();self.assertEqual(r['state'],'repair_queued')
        self.assertEqual(self.request()['state'],'already_repairing')
        with patch('council.codex_call',side_effect=self.model):self.s.recovery.repair(self.row(r['repair_id']))
        after=self.s.autopilot.get(self.session['id']);self.assertEqual(after['config'],before['config']);self.assertEqual(after['id'],before['id'])
        self.assertNotIn('watchdog_repair_id',after['progress']);self.assertTrue((self.work/'watchdog-recovery.json').is_file())
        self.assertEqual(self.row(r['repair_id'])['state'],'awaiting_progress')
        with self.s.store._connect() as c:
            folder=self.folder.parent/'OFFLINE-retry';folder.mkdir()
            c.execute('INSERT INTO research_jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',('OFFLINE-retry',self.f.project['id'],self.f.project['id'],'OFFLINE','running','verification','OFFLINE retry','lite',json.dumps(self.config),str(folder),now(),now(),None,None))
        self.s.recovery.verify();self.assertEqual(self.row(r['repair_id'])['state'],'awaiting_progress')
        (folder/'broad-exploration-receipt.json').write_text('{"agents":6,"fixture":true}')
        self.s.recovery.verify();self.assertEqual(self.row(r['repair_id'])['state'],'verified')
    def test_pause_cancels_repair_without_resuming_or_calling_models(self):
        r=self.request();self.s.autopilot.control(dict(project_id=self.f.project['id'],action='pause'))
        with patch('council.codex_call',side_effect=AssertionError('Paused project must not call models')):self.s.recovery.repair(self.row(r['repair_id']))
        self.assertEqual(self.row(r['repair_id'])['state'],'interrupted');self.assertEqual(self.s.autopilot.get(self.session['id'])['status'],'paused')
    def test_active_gpu_run_is_never_interrupted_for_diagnosis(self):
        import sqlite3
        with sqlite3.connect(self.f.db) as c:c.execute('INSERT INTO experiment_runs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',('OFFLINE-run','OFFLINE-plan','approval',self.f.project['id'],'epoch','running',1800,now(),now(),None,None,None,str(self.folder),'{}',None))
        self.assertEqual(self.request()['state'],'waiting_for_experiment')
    def test_unknown_host_bug_holds_instead_of_uncontrolled_repeat(self):
        r=self.request()
        with patch('council.codex_call',return_value=dict(action='needs_host_patch',root_cause='OFFLINE unknown host bug',repair_instructions=['Inspect host'],checks=[])):
            self.s.recovery.repair(self.row(r['repair_id']))
        self.assertEqual(self.row(r['repair_id'])['state'],'needs_attention');self.assertGreater(self.s.autopilot.get(self.session['id'])['progress']['watchdog_wait_until'],time.time())
        self.assertEqual(self.request()['state'],'cooldown')

    def test_old_incident_cannot_redispatch_a_completed_study(self):
        with self.s.store._connect() as c:c.execute("UPDATE research_jobs SET state='completed',phase='native-completed' WHERE id='OFFLINE-failed'")
        self.assertEqual(self.request()['state'],'completed_work_retained')
        with self.s.store._connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM watchdog_repairs').fetchone()[0],0)

    def test_stall_suspicion_does_not_cancel_a_valid_slow_native_call(self):
        with self.s.store._connect() as c:c.execute("UPDATE research_jobs SET state='running' WHERE id='OFFLINE-failed'")
        r=self.s.recovery.request(dict(session_id=self.session['id'],kind='stalled'))
        self.assertEqual(r['state'],'within_native_operation_allowance')

    def test_retry_specific_ids_do_not_bypass_diagnosis_cooldown(self):
        original=self.trace.read_text();self.trace.write_text(original.replace('must be an array','must be an array in 11111111-1111-4111-8111-111111111111'))
        r=self.request();row=self.row(r['repair_id']);self.s.recovery.set(r['repair_id'],'failed',json.loads(row['payload']))
        self.trace.write_text(original.replace('must be an array','must be an array in 22222222-2222-4222-8222-222222222222'))
        self.assertEqual(self.request()['state'],'cooldown')

    def test_preflight_diagnosis_receives_actual_stack_when_native_trace_is_absent(self):
        from watchdog_recovery import evidence
        self.trace.unlink()
        error='Traceback (most recent call last):\n  File "native_pipeline.py", line 105, in session_skill_receipts\nAttributeError: string has no get'
        (self.folder/'error.log').write_text(error)
        proof=evidence(dict(id='OFFLINE-failed',run_dir=str(self.folder),phase='preflight',message='string has no get'))
        self.assertIsNone(proof['raw_trace']);self.assertEqual(proof['logs']['error.log'],error)

    def test_host_patch_launch_retains_hold_until_detached_worker_finishes(self):
        r=self.request()
        def diagnose(*args):
            value=self.model(*args);value['action']='needs_host_patch';return value
        with patch('council.codex_call',side_effect=diagnose),patch('host_repair.launch',return_value=dict(pid=12345)) as launched:
            self.s.recovery.repair(self.row(r['repair_id']))
        launched.assert_called_once_with(self.s.store.db_path,r['repair_id'])
        self.assertEqual(self.row(r['repair_id'])['state'],'patching')
        self.assertEqual(self.s.autopilot.get(self.session['id'])['progress']['watchdog_repair_id'],r['repair_id'])

    def test_worker_repair_is_verified_only_after_a_real_successful_tool_result(self):
        r=self.request();data=json.loads(self.row(r['repair_id'])['payload']);data['expected_tool']='worker'
        self.s.recovery.set(r['repair_id'],'awaiting_progress',data)
        folder=self.folder.parent/'OFFLINE-worker-retry';folder.mkdir()
        with self.s.store._connect() as c:
            c.execute('INSERT INTO research_jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',('OFFLINE-worker-retry',self.f.project['id'],self.f.project['id'],'OFFLINE','running','native-pipeline','retry','lite',json.dumps(self.config),str(folder),now(),now(),None,None))
        trace=folder/'native.stdout.jsonl';trace.write_text(json.dumps(dict(message='started'))+'\n')
        self.s.recovery.verify();self.assertEqual(self.row(r['repair_id'])['state'],'awaiting_progress')
        trace.write_text(json.dumps(dict(message=dict(content=[dict(type='tool_use',id='ctx',name='mcp__codex__context')])))+'\n'+json.dumps(dict(message=dict(content=[dict(type='tool_result',tool_use_id='ctx',content='OFFLINE actual successful context receipt')])))+'\n')
        self.s.recovery.verify();self.assertEqual(self.row(r['repair_id'])['state'],'verified')


class LiteratureInputTests(unittest.TestCase):
    def test_alias_only_sources_join_matching_candidates_and_preserve_raw(self):
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);work=root/'input';work.mkdir()
            (work/'LITERATURE.md').write_text('OFFLINE evidence')
            raw=dict(papers=[dict(canonical_id='arxiv:2601.00001',arxiv_id=None,abs_url='https://arxiv.org/abs/2601.00001')])
            (work/'source-evidence.json').write_text(json.dumps(raw))
            (work/'candidate_papers.json').write_text(json.dumps(dict(papers=[dict(id='2601.00001',abstract_excerpt='OFFLINE readable excerpt'),dict(id='2601.00002',abstract_excerpt='OFFLINE unused candidate')])))
            target=normalize(work,root/'repair');p=json.loads((target/'source-evidence.json').read_text())['papers'][0]
            self.assertEqual(p['arxiv_id'],'2601.00001');self.assertEqual(p['source_excerpt'],'OFFLINE readable excerpt')
            self.assertNotIn('verification_status',p);self.assertEqual(json.loads((work/'source-evidence.json').read_text()),raw)
            self.assertEqual(len(json.loads((target/'normalization.json').read_text())['excluded_candidates']),1)
            (work/'candidate_papers.json').write_text('[{"id":"DIFFERENT"}]')
            with self.assertRaisesRegex(ValueError,'식별자'):normalize(work,root/'repair')
