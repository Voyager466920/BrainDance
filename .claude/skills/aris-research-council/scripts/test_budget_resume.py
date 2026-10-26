"""Shared-budget admission and lossless recovery of a pre-commit Council stop."""
import json
import tempfile
import unittest
from pathlib import Path

from council import Budget,frozen_parent
import test_research as fixtures


class SharedBudgetTests(unittest.TestCase):
    def test_project_budget_is_authoritative_without_resetting_usage(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);ledger=root/'session.json'
            ledger.write_text(json.dumps(dict(calls=0,max_calls=5,token_budget=1000,charges={})))
            config=dict(max_model_calls=4,token_budget=50,session_budget=str(ledger))
            budget=Budget(config,root/'usage.json');budget.reserve(1,200)
            budget.record(dict(stage_path='actual-stage',total_tokens=250))
            reopened=Budget(config,budget.path);reopened.record(dict(stage_path='actual-stage',total_tokens=250))
            self.assertEqual(json.loads(ledger.read_text())['calls'],1)
            self.assertEqual(sum(json.loads(ledger.read_text())['charges'].values()),250)
            reopened.reserve(1,700)
            before=ledger.read_bytes()
            with self.assertRaises(RuntimeError):reopened.reserve(1,51)
            self.assertEqual(ledger.read_bytes(),before)
            self.assertEqual(json.loads(budget.path.read_text())['token_budget'],1000)
            self.assertEqual(json.loads(budget.path.read_text())['stage_default_token_budget'],50)
            standalone=Budget(dict(max_model_calls=4,token_budget=50),root/'standalone.json')
            with self.assertRaises(RuntimeError):standalone.reserve(1,200)


RETRY_FIXTURE=r'''
import json,sys
from pathlib import Path
job=json.loads(Path(sys.argv[1]).read_text());root=Path(sys.argv[1]).parent
if not job.get('resume_existing'):
 folder=root/'council';folder.mkdir()
 for name,data in [('config.json',{}),('run-inputs.json',{}),('run-state.json',{}),('usage.json',{}),('status.json',{'status':'failed'})]:
  (folder/name).write_text(json.dumps(data))
 print('ORIGINAL_PARTIAL_RUN_LOG',flush=True)
 state='failed';phase='chairman';message='Token admission budget exhausted before dispatch';exit_code=1
else:
 assert job['resume_attempt']==1
 assert (root/'attempts/1/worker.stdout.log').read_text().strip()=='ORIGINAL_PARTIAL_RUN_LOG'
 state='completed';phase='approval';message='OFFLINE continuation fixture';exit_code=0
(root/'progress.json').write_text(json.dumps(dict(state=state,phase=phase,message=message,updated_at='fixture')))
sys.exit(exit_code)
'''


class ResearchRetryTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.ResearchTests('test_start_records_actual_fixture_progress_and_exports_receipt')
        self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.fixture.fixture.write_text(RETRY_FIXTURE)

    def test_retry_retains_job_session_usage_and_original_failure_logs(self):
        f=self.fixture;ledger=f.root/'session.json';ledger.write_text(json.dumps(dict(calls=7,max_calls=24,token_budget=1500000,charges={'previous':400000})))
        job=f.engine.start(dict(node_id=f.node['id'],confirm=True),internal=dict(session_budget=str(ledger)))
        failed=f.wait(job);self.assertEqual(failed['state'],'failed');self.assertTrue(f.engine.can_retry(failed))
        root=Path(failed['run_dir']);(root/'council/run-state.json').write_text('{"tree_commit_started":true}')
        self.assertFalse(f.engine.can_retry(failed))
        (root/'council/run-state.json').write_text('{}')
        before=ledger.read_bytes();old_session=failed['config']['project_session']
        retried=f.engine.retry(job['id']);finished=f.wait(retried)
        self.assertEqual(finished['id'],job['id']);self.assertEqual(finished['state'],'completed')
        self.assertEqual(finished['config']['project_session'],old_session);self.assertEqual(ledger.read_bytes(),before)
        self.assertTrue((root/'attempts/1/job.json').exists());self.assertIn('ORIGINAL_PARTIAL_RUN_LOG',(root/'attempts/1/worker.stdout.log').read_text())


class FrozenParentTests(unittest.TestCase):
    def test_retry_uses_original_timestamp_but_rejects_actual_research_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);original=dict(id='same',title='Original question',metadata=dict(metric='nll'),updated_at='before')
            self.assertEqual(frozen_parent(folder,original,False),original)
            later={**original,'updated_at':'after'}
            self.assertEqual(frozen_parent(folder,later,True),original)
            before=(folder/'parent-snapshot.json').read_bytes()
            with self.assertRaises(ValueError):frozen_parent(folder,{**later,'title':'Different question'},True)
            self.assertEqual((folder/'parent-snapshot.json').read_bytes(),before)

    def test_legacy_snapshot_is_recovered_from_an_actual_prior_request(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);request=folder/'generation/codex/request.json';request.parent.mkdir(parents=True)
            original=dict(id='original',title='Same research',updated_at='first')
            serialized=json.dumps(original,ensure_ascii=False)
            request.write_text(json.dumps(dict(params=dict(arguments=dict(prompt='Goal\nExpand this parent hypothesis: '+serialized+'\nEvidence')))))
            recovered=frozen_parent(folder,{**original,'updated_at':'later'},True)
            self.assertEqual(json.dumps(recovered,ensure_ascii=False),serialized)

    def test_missing_input_does_not_silently_reuse_unverifiable_participant_output(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);cached=folder/'generation/claude/parsed.json';cached.parent.mkdir(parents=True);cached.write_text('{}')
            with self.assertRaises(ValueError):frozen_parent(folder,dict(id='same',updated_at='now'),True)


if __name__=='__main__':unittest.main()
