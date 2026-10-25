"""Permanent deletion only against disposable temporary databases and CPU files."""
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from compute import ComputeSettings
from experiments import ExperimentEngine, TERMINAL
from project_cleanup import ProjectCleanup
from tree_store import TreeStore


class ProjectCleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.store=TreeStore(self.root/'tree.sqlite3')
        self.node=self.store.add_node(None,'Delete target',kind='problem')
        self.other=self.store.add_node(None,'Keep this project',kind='problem')
        self.compute=ComputeSettings(self.root/'compute.json')
        for node in (self.node,self.other):
            self.compute.assign(node['project_id'],dict(profile_id='local',device_ids=['cpu'],time_budget_minutes=1))
        self.engine=ExperimentEngine(self.store,self.compute,self.compute.state)
        self.addCleanup(self.engine.close)
        self.cleanup=ProjectCleanup(self.store,self.engine,self.compute)

    def run_cpu(self):
        experiment=self.engine.create(dict(node_id=self.node['id'],title='CPU cleanup fixture',timeout_seconds=5,
            code="import os\nfrom pathlib import Path\nprint('retained log')\nPath(os.environ['BRAINDANCE_ARTIFACT_DIR'],'result.bin').write_bytes(b'x'*3000000)"))
        approval=self.engine.approve(experiment['id'],experiment['digest'],True)
        run=self.engine.enqueue(experiment['id'],approval['id'])
        deadline=time.monotonic()+8
        while time.monotonic()<deadline:
            if self.engine.run_info(run['id'])['state'] in TERMINAL and run['id'] not in self.engine.jobs:
                return run
            time.sleep(.03)
        self.fail('CPU fixture did not finish')

    def trash(self):
        self.store.set_project_deleted(self.node['project_id'],True)

    def purge(self):
        return self.cleanup.purge(self.node['project_id'],'Delete target')

    def test_purge_removes_owned_files_records_orphan_transcripts_and_reclaims_database(self):
        run=self.run_cpu();run_dir=Path(run['run_dir'])
        self.store.add_node(self.node['id'],'Nested hypothesis')
        for index in range(20):self.store.add_note(self.node['id'],'memo','Large private record '+str(index),'z'*100000)
        owned=self.root/'council-runs/owned';owned.mkdir(parents=True);(owned/'raw.txt').write_text('private original')
        shared=self.root/'council-runs/shared';shared.mkdir();(shared/'raw.txt').write_text('shared original')
        external=self.root/'external-dataset';external.mkdir();(external/'data').write_text('keep dataset')
        self.store.update_node(self.node['id'],metadata={'run':str(owned),'council_run':str(shared)})
        self.store.update_node(self.other['id'],metadata={'council_run':str(shared)})
        for ref in (str(owned),str(shared)):
            self.store.record_message(dict(id=ref,run_id=ref,round=1,phase='generation',participant='Claude',direction='response',content='original conversation',source='source.txt',created_at='2026-10-25'))
        # An artifact symlink must be unlinked without deleting its external target.
        (run_dir/'artifacts/dataset-link').symlink_to(external,target_is_directory=True)
        self.trash();preview=self.cleanup.preview(self.node['project_id'])
        self.assertGreaterEqual(preview['local_file_bytes'],3000000)
        self.assertEqual(preview['counts']['nodes'],2)
        result=self.purge();self.assertFalse(result['cleanup_pending'])
        self.assertGreaterEqual(result['removed_file_bytes'],3000000)
        self.assertGreater(result['reclaimed_database_bytes'],1000000)
        self.assertFalse(run_dir.exists());self.assertFalse(owned.exists())
        self.assertTrue((shared/'raw.txt').exists());self.assertTrue((external/'data').exists())
        tree=self.store.export_json();self.assertEqual(len(tree['projects']),1)
        self.assertEqual(tree['projects'][0]['id'],self.other['project_id'])
        self.assertEqual(tree['experiments'],[]);self.assertEqual(tree['experiment_runs'],[])
        self.assertEqual(tree['experiment_approvals'],[]);self.assertEqual(tree['cleanup_pending'],[])
        self.assertEqual(self.store.get_messages([str(owned)]),[])
        self.assertEqual(len(self.store.get_messages([str(shared)])),1)
        self.assertNotIn(self.node['project_id'],self.compute.state()['assignments'])
        self.assertIn(self.other['project_id'],self.compute.state()['assignments'])
        snapshot=json.loads((self.root/'tree.json').read_text())
        self.assertNotIn('Large private record',json.dumps(snapshot))
        with self.assertRaises(KeyError):self.store.set_project_deleted(self.node['project_id'],False)
        with self.store._connect() as conn:self.assertEqual(list(conn.execute('PRAGMA foreign_key_check')),[])

    def test_requires_trashed_project_and_matching_confirmation(self):
        with self.assertRaises(ValueError):self.purge()
        self.trash()
        with self.assertRaises(ValueError):self.cleanup.purge(self.node['project_id'],'wrong title')
        self.assertEqual(len(self.store.export_json()['projects']),2)
        self.assertEqual(self.cleanup.trash()['projects'][0]['id'],self.node['id'])

    def test_partial_file_cleanup_is_visible_and_retry_survives_reopening(self):
        run=self.run_cpu();self.trash()
        with patch('project_cleanup.shutil.rmtree',side_effect=PermissionError('fixture denied')):
            result=self.purge()
        self.assertTrue(result['cleanup_pending']);self.assertIn('fixture denied',result['error'])
        self.assertTrue(Path(run['run_dir']).exists())
        self.assertEqual(len(self.store.export_json()['cleanup_pending']),1)
        reopened=ProjectCleanup(TreeStore(self.root/'tree.sqlite3'),self.engine,self.compute)
        self.assertTrue(reopened.trash()['projects'][0]['cleanup_pending'])
        self.assertTrue(reopened.preview(self.node['project_id'])['cleanup_pending'])
        result=reopened.purge(self.node['project_id'],'Delete target')
        self.assertFalse(result['cleanup_pending']);self.assertFalse(Path(run['run_dir']).exists())
        self.assertEqual(reopened.trash()['projects'],[])

    def test_settings_write_failure_remains_retryable_without_touching_profiles(self):
        self.trash();profiles=self.compute.state()['profiles']
        with patch.object(self.compute,'_save',side_effect=OSError('fixture settings failure')):
            self.assertTrue(self.purge()['cleanup_pending'])
        self.assertIn(self.node['id'],self.compute.state()['assignments'])
        self.assertFalse(self.purge()['cleanup_pending'])
        self.assertEqual(profiles,self.compute.state()['profiles'])

    def test_arbitrary_run_directory_is_refused_before_any_deletion(self):
        run=self.run_cpu();outside=self.root/'do-not-delete';outside.mkdir()
        with self.store._connect() as conn:conn.execute('UPDATE experiment_runs SET run_dir=? WHERE id=?',(str(outside),run['id']))
        self.trash()
        with self.assertRaises(ValueError):self.purge()
        self.assertTrue(outside.exists());self.assertEqual(len(self.store.export_json()['projects']),2)

    def test_symlinked_managed_parent_is_refused(self):
        self.run_cpu();self.trash()
        actual=self.root/'experiment-runs';moved=self.root/'outside-runs';actual.rename(moved);actual.symlink_to(moved,target_is_directory=True)
        with self.assertRaises(ValueError):self.purge()
        self.assertEqual(len(self.store.export_json()['projects']),2)

    def test_queued_and_finishing_runs_block_purge(self):
        self.engine.stop_event.set();self.engine.thread.join(timeout=2)
        experiment=self.engine.create(dict(node_id=self.node['id'],title='queued fixture',code='print(1)',timeout_seconds=1))
        approval=self.engine.approve(experiment['id'],experiment['digest'],True)
        run=self.engine.enqueue(experiment['id'],approval['id']);self.trash()
        with self.assertRaises(ValueError):self.purge()
        self.engine._finish(run['id'],dict(state='cancelled',duration_seconds=0,exit_code=None))
        self.engine.jobs[run['id']]={'project_id':self.node['id']}
        try:
            with self.assertRaises(ValueError):self.purge()
        finally:self.engine.jobs.pop(run['id'])
        self.assertFalse(self.purge()['cleanup_pending'])
