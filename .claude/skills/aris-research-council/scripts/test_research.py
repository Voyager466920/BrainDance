"""Real supervisor subprocesses with explicit offline worker fixtures, no model calls."""
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from compute import ComputeSettings
from experiments import ExperimentEngine
from project_cleanup import ProjectCleanup
from research import ResearchEngine,TERMINAL
from research_worker import verify,install_skill
from tree_store import TreeStore


FIXTURE='''import json,sys,time
from pathlib import Path
root=Path(sys.argv[1]).parent
def emit(state,phase):
 data=dict(state=state,phase=phase,message='OFFLINE FIXTURE '+phase,updated_at='2026-10-25')
 tmp=root/'progress.fixture.tmp';tmp.write_text(json.dumps(data));tmp.replace(root/'progress.json')
 with (root/'progress.jsonl').open('a') as log:log.write(json.dumps(dict(at='2026-10-25',**data))+'\\n')
emit('running','literature')
time.sleep(DELAY)
(root/'literature').mkdir()
(root/'literature/LITERATURE.md').write_text('OFFLINE test output')
emit('completed','approval')
'''


class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.store=TreeStore(self.root/'tree.sqlite3')
        self.node=self.store.add_node(None,'Offline research fixture',kind='problem')
        self.engine=ResearchEngine(self.store);self.addCleanup(self.engine.close)
        self.fixture=self.root/'fixture.py';self.fixture.write_text(FIXTURE.replace('DELAY','.4'))
        self.patch1=patch.object(self.engine,'command',return_value=[sys.executable,str(self.fixture)]);self.patch1.start();self.addCleanup(self.patch1.stop)
        self.patch2=patch.object(self.engine,'availability',return_value=dict(available=True,missing=[],aris_repo=str(self.root/'aris')));self.patch2.start();self.addCleanup(self.patch2.stop)

    def start(self,**extra):return self.engine.start({**dict(node_id=self.node['id'],confirm=True),**extra})

    def wait(self,job):
        deadline=time.monotonic()+6
        while time.monotonic()<deadline:
            current=self.engine.get(job['id'])
            if current['state'] in TERMINAL and self.engine.active_id is None:return current
            time.sleep(.03)
        self.fail('Supervisor fixture did not finish')

    def test_start_records_actual_fixture_progress_and_exports_receipt(self):
        job=self.start();self.assertEqual(job['state'],'queued');self.assertEqual(job['mode'],'balanced')
        self.assertEqual(self.start()['id'],job['id'])
        current=self.wait(job);self.assertEqual(current['state'],'completed')
        info=self.engine.info(job['id']);self.assertTrue(info['events']);self.assertEqual(info['events'][0]['phase'],'literature')
        self.assertEqual(self.engine.file(job['id'],'literature/LITERATURE.md').read_text(),'OFFLINE test output')
        with self.assertRaises(KeyError):self.engine.file(job['id'],'../../compute.json')
        snapshot=json.loads((self.root/'tree.json').read_text());self.assertEqual(snapshot['research_jobs'][0]['state'],'completed')
        self.assertFalse(snapshot['experiment_runs'])

    def test_literature_only_worker_stops_after_source_verification_and_shared_report(self):
        import research_worker
        jobroot=self.root/'literature-only';jobroot.mkdir();spec=jobroot/'job.json'
        spec.write_text(json.dumps(dict(id='offline-literature',task='literature',db=str(self.store.db_path),node_id=self.node['id'])))
        def discover(*_):
            work=jobroot/'literature';work.mkdir()
            (work/'LITERATURE.md').write_text('OFFLINE verified-source fixture, not scientific findings')
            return work
        def verify_fixture(job,root,work,progress):
            evidence=work/'verified-evidence.json';evidence.write_text('{"papers":[]}');return evidence
        with patch('research_worker.signal.signal'),patch('research_worker.literature',side_effect=discover),patch('research_worker.verify',side_effect=verify_fixture),patch('research_worker.council.run',side_effect=AssertionError('No full Council in literature-only mode')),patch('lab_worker.prepare',side_effect=AssertionError('No experiment preparation')):
            self.assertEqual(research_worker.run(spec),0)
        result=json.loads((jobroot/'progress.json').read_text());self.assertEqual(result['state'],'completed');self.assertEqual(result['phase'],'literature-completed')
        self.assertTrue(any(note['title']=='논문 탐색 결과' for note in self.store.export_json()['notes']))
        self.assertEqual(self.store.export_json()['experiment_runs'],[])

    def test_worker_slot_stays_busy_until_snapshot_is_persisted(self):
        entered=threading.Event();release=threading.Event();original=self.store.export_json
        def delayed_export(*args,**kwargs):
            entered.set()
            if not release.wait(6):raise TimeoutError('snapshot release')
            return original(*args,**kwargs)
        with patch.object(self.store,'export_json',side_effect=delayed_export):
            job=self.start()
            try:
                self.assertTrue(entered.wait(6))
                self.assertEqual(self.engine.get(job['id'])['state'],'completed')
                self.assertEqual(self.engine.active_id,job['id'])
                with self.assertRaises(ValueError):self.start()
            finally:release.set()
            self.wait(job)
        snapshot=json.loads((self.root/'tree.json').read_text())
        self.assertEqual(snapshot['research_jobs'][0]['state'],'completed')

    def test_consent_and_resource_limits_prevent_dispatch(self):
        for extra in [dict(confirm=False),dict(mode='invented'),dict(token_budget=1),dict(phase_timeout_seconds=1)]:
            with self.assertRaises(ValueError):self.start(**extra)
        self.assertEqual(self.engine.list(self.node['project_id'])['jobs'],[])
        self.store.set_project_deleted(self.node['project_id'],True)
        with self.assertRaises(ValueError):self.start()

    def test_stop_and_project_trash_terminate_the_worker(self):
        self.fixture.write_text(FIXTURE.replace('DELAY','30'))
        job=self.start();time.sleep(.2);self.engine.stop(job['id'])
        self.assertEqual(self.wait(job)['state'],'cancelled')
        job=self.start();time.sleep(.2);self.store.set_project_deleted(self.node['project_id'],True)
        self.assertEqual(self.wait(job)['state'],'cancelled')

    def test_process_failure_is_not_completed_and_missing_receipt_is_explicit(self):
        self.fixture.write_text('raise RuntimeError("offline fixture failure")')
        result=self.wait(self.start());self.assertEqual(result['state'],'failed')
        self.assertIn('영수증',result['error'])

    def test_shutdown_and_restart_do_not_repeat_previous_model_dispatch(self):
        self.fixture.write_text(FIXTURE.replace('DELAY','30'))
        job=self.start();time.sleep(.2);self.engine.close()
        self.assertEqual(self.engine.get(job['id'])['state'],'cancelled')
        with self.store._connect() as conn:conn.execute("UPDATE research_jobs SET state='running' WHERE id=?",(job['id'],))
        reopened=ResearchEngine(self.store)
        try:self.assertEqual(reopened.get(job['id'])['state'],'interrupted');self.assertIsNone(reopened.active_id)
        finally:reopened.close()

    def test_purge_removes_owned_research_files_but_blocks_running_jobs(self):
        self.fixture.write_text(FIXTURE.replace('DELAY','30'))
        job=self.start();time.sleep(.2)
        compute=ComputeSettings(self.root/'compute.json');experiments=ExperimentEngine(self.store,compute,compute.state)
        self.addCleanup(experiments.close);cleanup=ProjectCleanup(self.store,experiments,compute,self.engine)
        self.store.set_project_deleted(self.node['project_id'],True)
        with self.assertRaises(ValueError):cleanup.preview(self.node['project_id'])
        self.wait(job)
        result=cleanup.purge(self.node['project_id'],'Offline research fixture')
        self.assertFalse(result['cleanup_pending']);self.assertFalse(Path(job['run_dir']).exists())
        self.assertEqual(self.store.export_json()['research_jobs'],[])

    def test_official_skill_copy_and_missing_evidence_fail_before_council(self):
        aris=self.root/'aris';(aris/'skills/research-lit').mkdir(parents=True);(aris/'skills/shared-references').mkdir()
        (aris/'skills/research-lit/SKILL.md').write_text('UPSTREAM FIXTURE unchanged')
        work=self.root/'literature';work.mkdir();receipt=install_skill(aris,work)
        self.assertEqual(len(receipt),64)
        self.assertEqual((work/'.aris-official/skills/research-lit/SKILL.md').read_text(),'UPSTREAM FIXTURE unchanged')
        with self.assertRaises(ValueError):verify(dict(aris_repo=str(aris)),self.root,work,None)

    def test_verified_literature_is_reused_only_for_the_same_goal(self):
        first=self.start();self.wait(first)
        folder=Path(first['run_dir']);lit=folder/'literature'
        (lit/'verified-evidence.json').write_text('{"papers":[]}')
        (folder/'literature-usage.json').write_text('{"skill_invoked":true}')
        second=self.start();self.assertEqual(second['config']['reuse_literature']['job_id'],first['id']);self.wait(second)
        third=self.start(reuse_literature=False);self.assertIsNone(third['config']['reuse_literature']);self.wait(third)
        self.store.update_node(self.node['id'],metadata={'research_goal':'Different offline topic'})
        fourth=self.start();self.assertIsNone(fourth['config']['reuse_literature']);self.wait(fourth)
