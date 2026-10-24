import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from compute import ComputeSettings, fingerprint, ssh_command, validate_profile, timestamp


class ComputeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store=ComputeSettings(Path(self.temp.name)/'config/compute.json')
        self.profile=dict(name='GPU server',kind='ssh',host='gpu-server',user='research',port=2222)

    def test_ssh_is_bounded_readonly_and_rejects_option_or_shell_injection(self):
        with self.assertRaises(ValueError):self.store.save_profile({**self.profile,'id':'local'})
        argv=ssh_command(self.profile)
        self.assertIn('StrictHostKeyChecking=yes',argv)
        self.assertIn('BatchMode=yes',argv)
        self.assertIn('ClearAllForwardings=yes',argv)
        self.assertEqual(argv[-2],'research@gpu-server')
        self.assertTrue(argv[-1].startswith('python3 -c '))
        for field,value in [('host','-oProxyCommand=evil'),('host','a;touch /tmp/bad'),('user','$(evil)'),('port',True)]:
            with self.assertRaises(ValueError):validate_profile({**self.profile,field:value})

    def test_gpu_assignment_persists_without_launching_and_invalidates_changed_host(self):
        profile=self.store.save_profile(self.profile)
        devices=[dict(id='cpu',kind='cpu',name='CPU'),dict(id='GPU-a',name='GPU',kind='cuda')]
        self.store.inventories[profile['id']]=dict(connected=True,devices=devices,fingerprint=fingerprint(profile),checked_at=timestamp())
        assignment=self.store.assign('project',dict(profile_id=profile['id'],device_ids=['GPU-a'],max_parallel_runs=2,time_budget_minutes=10))
        self.assertFalse(assignment['auto_run'])
        self.assertTrue(assignment['require_approval'])
        reloaded=ComputeSettings(self.store.path).state()
        self.assertEqual(reloaded['assignments']['project']['device_ids'],['GPU-a'])
        self.assertFalse(reloaded['execution_available'])
        self.assertEqual(self.store.path.stat().st_mode&0o777,0o600)
        self.store.save_profile({**profile,'host':'other-server'})
        self.assertEqual(self.store.state()['assignments']['project']['device_ids'],[])
        with self.assertRaises(ValueError):self.store.assign('project',dict(profile_id=profile['id'],device_ids=['GPU-a']))

    def test_unknown_devices_mixed_cpu_gpu_and_auto_execution_are_rejected(self):
        for payload in [dict(device_ids=['GPU-invented']),dict(device_ids=['cpu','GPU-a']),
                        dict(device_ids=['cpu'],auto_run=True),dict(device_ids=['cpu'],max_parallel_runs=True),
                        dict(device_ids=['cpu'],time_budget_minutes=0)]:
            with self.assertRaises(ValueError):self.store.assign('p',dict(profile_id='local',**payload))
        self.assertEqual(self.store.assign('p',dict(profile_id='local',device_ids=['cpu']))['device_ids'],['cpu'])

    def test_remote_probe_uses_only_fixed_discovery_and_retains_errors(self):
        profile=self.store.save_profile(self.profile)
        result=subprocess.CompletedProcess([],0,json.dumps(dict(platform='Linux',devices=[dict(id='GPU-a',name='A',kind='cuda')])), '')
        with patch('compute.subprocess.run',return_value=result) as run:
            inventory=self.store.probe(profile['id'])
            self.assertTrue(inventory['connected'])
            self.assertEqual(run.call_args.args[0],ssh_command(profile))
        reloaded=ComputeSettings(self.store.path)
        self.assertEqual(reloaded.state()['inventories'][profile['id']]['devices'][0]['id'],'GPU-a')
        with patch('compute.subprocess.run',return_value=subprocess.CompletedProcess([],255,'','Host key verification failed.')):
            failed=self.store.probe(profile['id'])
            self.assertFalse(failed['connected'])
            self.assertIn('Host key verification failed.',failed['error'])
        self.assertIn('Host key verification failed.',self.store.path.with_name('compute-events.jsonl').read_text())

    def test_bundled_app_runs_fixed_probe_without_python_interpreter_flags(self):
        result=subprocess.CompletedProcess([],0,json.dumps(dict(platform='Darwin',devices=[dict(id='cpu',name='CPU',kind='cpu')])), '')
        with patch('compute.sys.frozen',True,create=True), patch('compute.subprocess.run',return_value=result) as run:
            self.assertTrue(self.store.probe('local')['connected'])
            self.assertEqual(run.call_args.args[0][1:],['--probe-local'])


if __name__=='__main__':unittest.main()
