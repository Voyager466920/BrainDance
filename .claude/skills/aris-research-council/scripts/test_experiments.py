"""Real CPU subprocesses in temporary workspaces; no models or physical GPU use."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from compute import ComputeSettings,fingerprint,timestamp
from experiments import ExperimentEngine,TERMINAL,worker_source,summarize
from tree_store import TreeStore

SUCCESS="""import json,os
from pathlib import Path
print('raw stdout',flush=True)
print('raw stderr',file=__import__('sys').stderr,flush=True)
root=Path(os.environ['BRAINDANCE_ARTIFACT_DIR'])
(root/'result.txt').write_text('actual artifact')
Path(os.environ['BRAINDANCE_METRICS_PATH']).write_text(json.dumps({'baseline':{'accuracy':.5},'candidate':{'accuracy':.75}}))
"""


@unittest.skipUnless(os.name=='posix','POSIX process groups are required')
class ExperimentTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.store=TreeStore(self.root/'tree.sqlite3')
        self.node=self.store.add_node(None,'Executor tests',kind='problem')
        self.compute=ComputeSettings(self.root/'compute.json')
        self.policy=dict(profile_id='local',device_ids=['cpu'],time_budget_minutes=1,max_parallel_runs=1,auto_run=False)
        self.compute.assign(self.node['project_id'],self.policy)
        self.engine=ExperimentEngine(self.store,self.compute,self.compute.state)
        self.addCleanup(self.engine.close)

    def create(self,code=SUCCESS,timeout=5,**fields):
        return self.engine.create(dict(node_id=self.node['id'],title='CPU experiment',code=code,timeout_seconds=timeout,**fields))

    def run_experiment(self,experiment):
        approval=self.engine.approve(experiment['id'],experiment['digest'],True)
        return self.engine.enqueue(experiment['id'],approval['id'])

    def wait(self,run,timeout=10):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            current=self.engine.run_info(run['id'])
            if current['state'] in TERMINAL:return current
            time.sleep(.03)
        self.fail('Run did not finish: '+str(current))

    def wait_running(self,run):
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            current=self.engine.run_info(run['id'])
            if current['state']=='running' and (Path(run['run_dir'])/'stdout.log').exists():return current
            time.sleep(.02)
        self.fail('Run did not start')

    def test_real_process_receipts_metrics_files_and_journal_are_preserved(self):
        experiment=self.create();run=self.run_experiment(experiment);result=self.wait(run)
        self.assertEqual(result['state'],'succeeded');self.assertEqual(result['exit_code'],0)
        self.assertIn('raw stdout',result['stdout_tail']);self.assertIn('raw stderr',result['stderr_tail'])
        self.assertEqual(result['result']['analysis']['delta'],.25)
        artifact=next(a for a in result['result']['artifacts'] if a['path']=='artifacts/result.txt')
        self.assertEqual(hashlib.sha256(self.engine.file(run['id'],artifact['path']).read_bytes()).hexdigest(),artifact['sha256'])
        self.assertEqual(self.engine.file(run['id'],'experiment.py').read_text(),SUCCESS)
        snapshot=json.loads((self.root/'tree.json').read_text())
        self.assertEqual(snapshot['experiment_runs'][0]['state'],'succeeded')
        self.assertTrue(any(n['kind']=='result' and run['id'] in n['content'] for n in snapshot['notes']))
        for name in ['../compute.json','/etc/passwd','artifacts/../../compute.json']:
            with self.assertRaises(KeyError):self.engine.file(run['id'],name)

    def test_no_approval_no_execution_and_exact_digest_is_required(self):
        experiment=self.create()
        with self.assertRaises(ValueError):self.engine.enqueue(experiment['id'],'invented')
        with self.assertRaises(ValueError):self.engine.approve(experiment['id'],experiment['digest'],False)
        with self.assertRaises(ValueError):self.engine.approve(experiment['id'],'changed',True)
        time.sleep(.25)
        self.assertEqual(self.engine.list(self.node['id'])['experiments'][0]['runs'],[])
        approval=self.engine.approve(experiment['id'],experiment['digest'],True)
        again=self.engine.approve(experiment['id'],experiment['digest'],True)
        self.assertEqual(approval['id'],again['id'])

    def test_duplicate_dispatch_of_one_approval_is_idempotent(self):
        experiment=self.create();approval=self.engine.approve(experiment['id'],experiment['digest'],True)
        first=self.engine.enqueue(experiment['id'],approval['id'])
        second=self.engine.enqueue(experiment['id'],approval['id'])
        self.assertEqual(first['id'],second['id']);self.assertEqual(self.wait(first)['state'],'succeeded')
        self.assertEqual(len(self.engine.list(self.node['id'])['experiments'][0]['runs']),1)

    def test_automatic_mode_only_consumes_approved_experiments_once(self):
        self.compute.assign(self.node['project_id'],{**self.policy,'auto_run':True})
        experiment=self.create();time.sleep(.3)
        self.assertEqual(self.engine.list(self.node['id'])['experiments'][0]['runs'],[])
        self.engine.approve(experiment['id'],experiment['digest'],True)
        deadline=time.monotonic()+5;rows=[]
        while not rows and time.monotonic()<deadline:
            rows=self.engine.list(self.node['id'])['experiments'][0]['runs'];time.sleep(.03)
        self.assertTrue(rows);self.assertEqual(self.wait(rows[0])['state'],'succeeded')
        time.sleep(.3)
        self.assertEqual(len(self.engine.list(self.node['id'])['experiments'][0]['runs']),1)

    def test_resource_change_invalidates_previously_approved_plan(self):
        experiment=self.create();approval=self.engine.approve(experiment['id'],experiment['digest'],True)
        self.compute.assign(self.node['project_id'],{**self.policy,'time_budget_minutes':2})
        with self.assertRaises(ValueError):self.engine.enqueue(experiment['id'],approval['id'])
        self.assertEqual(self.engine.list(self.node['id'])['experiments'][0]['runs'],[])

    def test_queue_reservation_cannot_oversubscribe_project_budget(self):
        self.engine.stop_event.set();self.engine.thread.join(timeout=2)
        first=self.create(timeout=40);approval=self.engine.approve(first['id'],first['digest'],True)
        self.engine.enqueue(first['id'],approval['id'])
        second=self.create(timeout=30);approval2=self.engine.approve(second['id'],second['digest'],True)
        with self.assertRaises(ValueError):self.engine.enqueue(second['id'],approval2['id'])
        budget=self.engine.list(self.node['id'])['budget']
        self.assertEqual(budget['reserved_seconds'],40);self.assertEqual(budget['remaining_seconds'],20)

    def test_timeout_and_manual_cancel_stop_process_group(self):
        long="import time\nprint('started',flush=True)\ntime.sleep(30)\n"
        timed=self.run_experiment(self.create(long,timeout=1))
        self.assertEqual(self.wait(timed)['state'],'timed_out')
        cancelled=self.run_experiment(self.create(long,timeout=10));self.wait_running(cancelled)
        self.engine.cancel(cancelled['id'])
        self.assertEqual(self.wait(cancelled)['state'],'cancelled')

    def test_nonzero_exit_and_missing_metrics_are_not_fabricated_success(self):
        failed=self.wait(self.run_experiment(self.create("raise RuntimeError('real failure')")))
        self.assertEqual(failed['state'],'failed');self.assertNotEqual(failed['exit_code'],0)
        self.assertIn('real failure',failed['stderr_tail'])
        empty=self.wait(self.run_experiment(self.create("print('no metrics')")))
        self.assertEqual(empty['state'],'succeeded')
        self.assertEqual(empty['result']['analysis']['status'],'no_metrics')
        self.assertTrue(empty['result']['warnings'])

    def test_environment_does_not_inherit_account_secrets_and_cpu_masks_cuda(self):
        code="""import os,json
from pathlib import Path
assert 'OPENAI_API_KEY' not in os.environ
assert 'ANTHROPIC_API_KEY' not in os.environ
assert os.environ['CUDA_VISIBLE_DEVICES']==''
assert os.environ['BRAINDANCE_DEVICE']=='cpu'
Path(os.environ['BRAINDANCE_METRICS_PATH']).write_text(json.dumps({'accuracy':1}))
"""
        with patch.dict(os.environ,OPENAI_API_KEY='test-secret',ANTHROPIC_API_KEY='another-secret'):
            self.assertEqual(self.wait(self.run_experiment(self.create(code)))['state'],'succeeded')

    def test_symlink_artifacts_are_not_collected(self):
        secret=self.root/'private.txt';secret.write_text('do not collect')
        code=SUCCESS+"\n(Path(os.environ['BRAINDANCE_ARTIFACT_DIR'])/'escape.txt').symlink_to("+repr(str(secret))+')\n'
        run=self.wait(self.run_experiment(self.create(code)))
        self.assertFalse(any(a['path'].endswith('escape.txt') for a in run['result']['artifacts']))
        with self.assertRaises(KeyError):self.engine.file(run['id'],'artifacts/escape.txt')

    def test_synthetic_training_template_actually_trains_and_reports_results(self):
        code=Path(__file__).resolve().parent.parent.joinpath('assets/experiment_template.py').read_text()
        result=self.wait(self.run_experiment(self.create(code)))
        self.assertEqual(result['state'],'succeeded')
        self.assertGreater(result['result']['analysis']['candidate'],result['result']['analysis']['baseline'])
        self.assertEqual(result['result']['metrics']['test_samples'],256)
        self.assertTrue(self.engine.file(result['id'],'artifacts/predictions.csv').is_file())

    def test_simulated_ssh_uses_real_worker_protocol_and_collects_remote_files(self):
        # The remote worker really runs, but transport is local: no SSH server is contacted.
        profile=self.compute.save_profile(dict(name='Test remote',kind='ssh',host='example.invalid'))
        inventory=dict(connected=True,devices=[dict(id='cpu',name='CPU',kind='cpu')],fingerprint=fingerprint(profile),checked_at=timestamp())
        self.compute.inventories[profile['id']]=inventory
        self.compute.assign(self.node['project_id'],{**self.policy,'profile_id':profile['id']})
        real_command=self.engine._transport(profile)
        self.assertEqual(real_command[0],'ssh');self.assertIn('StrictHostKeyChecking=yes',real_command)
        home=self.root/'remote-home';home.mkdir()
        wrapper='import os;os.environ["HOME"]='+repr(str(home))+'\n'+worker_source()
        with patch.object(self.engine,'_transport',return_value=[sys.executable,'-u','-c',wrapper]),patch.object(self.compute,'probe',return_value=inventory):
            result=self.wait(self.run_experiment(self.create()))
        self.assertEqual(result['state'],'succeeded')
        self.assertTrue(Path(result['result']['target_dir']).is_relative_to(home))
        self.assertEqual(self.engine.file(result['id'],'artifacts/result.txt').read_text(),'actual artifact')

    def test_project_trash_stops_job_but_retains_completion_note(self):
        run=self.run_experiment(self.create("import time\nprint('ready',flush=True)\ntime.sleep(30)",timeout=10));self.wait_running(run)
        self.store.set_project_deleted(self.node['project_id'],True)
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            with self.store._connect() as conn:state=conn.execute('SELECT state FROM experiment_runs WHERE id=?',(run['id'],)).fetchone()[0]
            if state in TERMINAL:break
            time.sleep(.05)
        self.assertEqual(state,'cancelled')
        self.store.set_project_deleted(self.node['project_id'],False)
        self.assertEqual(self.engine.run_info(run['id'])['state'],'cancelled')
        self.assertTrue(any(n['id']=='run:'+run['id'] for n in self.store.export_json()['notes']))

    def test_comparison_honors_metric_direction_without_claiming_significance(self):
        summary=summarize({'baseline':{'loss':3},'candidate':{'loss':2}},'loss','minimize')
        self.assertEqual(summary['observation'],'candidate_higher_ranked')
        self.assertIn('no statistical',summary['note'])

    def test_live_output_is_visible_before_completion(self):
        run=self.run_experiment(self.create("import time\nprint('live-progress',flush=True)\ntime.sleep(20)",timeout=5))
        deadline=time.monotonic()+3;seen=False
        while time.monotonic()<deadline:
            current=self.engine.run_info(run['id'])
            if 'live-progress' in current['stdout_tail']:
                seen=True;self.assertEqual(current['state'],'running');break
            time.sleep(.03)
        self.assertTrue(seen)
        self.engine.cancel(run['id']);self.assertEqual(self.wait(run)['state'],'cancelled')

    def test_concurrency_is_enforced_and_same_gpu_is_not_double_booked(self):
        self.compute.assign(self.node['project_id'],{**self.policy,'max_parallel_runs':2})
        runs=[self.run_experiment(self.create("import time\ntime.sleep(.4)",timeout=3)) for _ in range(3)]
        maximum=0;deadline=time.monotonic()+6
        while time.monotonic()<deadline:
            states=[self.engine.run_info(r['id'])['state'] for r in runs]
            maximum=max(maximum,states.count('running'))
            if all(s in TERMINAL for s in states):break
            time.sleep(.02)
        self.assertEqual(maximum,2)
        profile=self.compute.data['profiles'][0]
        inventory=dict(connected=True,devices=[dict(id='GPU-virtual',name='Virtual test device',kind='cuda')],fingerprint=fingerprint(profile),checked_at=timestamp())
        self.compute.inventories['local']=inventory
        self.compute.assign(self.node['project_id'],{**self.policy,'max_parallel_runs':2,'device_ids':['GPU-virtual']})
        with patch.object(self.compute,'probe',return_value=inventory):
            gpu_runs=[self.run_experiment(self.create("import time\ntime.sleep(.3)",timeout=3)) for _ in range(2)]
            maximum=0;deadline=time.monotonic()+6
            while time.monotonic()<deadline:
                states=[self.engine.run_info(r['id'])['state'] for r in gpu_runs]
                maximum=max(maximum,states.count('running'))
                if all(s in TERMINAL for s in states):break
                time.sleep(.02)
        self.assertEqual(maximum,1)  # No actual GPU is touched by the sleep-only processes.

    def test_restart_does_not_replay_an_ambiguous_running_job(self):
        self.engine.stop_event.set();self.engine.thread.join(timeout=2)
        experiment=self.create();run=self.run_experiment(experiment)
        with self.store._connect() as conn:conn.execute("UPDATE experiment_runs SET state='running' WHERE id=?",(run['id'],))
        Path(run['run_dir'],'stdout.log').write_text('retained partial output')
        self.engine.close()
        recovered=ExperimentEngine(self.store,self.compute,self.compute.state,autostart=False)
        self.addCleanup(recovered.close)
        result=recovered.run_info(run['id'])
        self.assertEqual(result['state'],'interrupted')
        self.assertIn('retained partial output',result['stdout_tail'])
        self.assertEqual(len(recovered.list(self.node['id'])['experiments'][0]['runs']),1)

    def test_output_overflow_stops_job_and_marks_truncation(self):
        result=self.wait(self.run_experiment(self.create("import sys\nsys.stdout.write('x'*(9*1024*1024))\nsys.stdout.flush()",timeout=5)))
        self.assertEqual(result['state'],'failed')
        self.assertTrue(result['result']['log_truncated']['stdout'])
        self.assertEqual(Path(result['run_dir'],'stdout.log').stat().st_size,8*1024*1024)


if __name__=='__main__':unittest.main()
