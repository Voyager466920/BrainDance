"""Isolated host patch acceptance/deployment controls, never live model/GPU work."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import host_repair as repair
import test_watchdog_recovery as fixtures


class PatchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.path=self.root/repair.SCRIPTS/'parser.py';self.path.parent.mkdir(parents=True)
        self.path.write_text('def parse(record):\n    return record["message"].get("content",[])\n\ndef unrelated():\n    return "preserved"\n')
        self.proof=dict(logs={'error.log':'Traceback:\n  File "parser.py", line 2, in parse\nAttributeError: str has no get'})
        self.targets=repair.target_sources(self.root,self.proof)
        self.edit=dict(path=str(Path(repair.SCRIPTS)/'parser.py'),old='return record["message"].get("content",[])',new='return record["message"].get("content",[]) if isinstance(record["message"],dict) else []')

    def test_exact_function_patch_keeps_unrelated_code_and_rejects_policy_edits(self):
        changed=repair.apply_edits(self.root,self.targets,[self.edit]);self.assertEqual(len(changed),1)
        code={};exec(self.path.read_text(),code)
        self.assertEqual(code['parse']({'message':'real system warning'}),[])
        self.assertEqual(code['parse']({'message':{'content':['kept']}}),['kept'])
        self.assertEqual(code['unrelated'](),'preserved')
        invalid={**self.edit,'path':str(Path(repair.SCRIPTS)/'session_budget.py')}
        with self.assertRaises(ValueError):repair.apply_edits(self.root,self.targets,[invalid])
        with self.assertRaisesRegex(ValueError,'outside'):
            repair.apply_edits(self.root,self.targets,[dict(path=self.edit['path'],old='return "preserved"',new='return "silently changed"')])

    def test_missing_stack_and_protected_core_are_not_guessed(self):
        with self.assertRaisesRegex(ValueError,'traceback'):repair.target_sources(self.root,dict(logs={}))
        with self.assertRaisesRegex(ValueError,'traceback'):repair.target_sources(self.root,dict(logs={'error.log':'File "session_budget.py", line 1, in check'}))

    def test_failed_checks_keep_the_old_runtime(self):
        with self.assertRaisesRegex(RuntimeError,'failed'):
            repair.checked([sys.executable,'-c','raise RuntimeError("OFFLINE regression failure")'],self.root,self.root,'regression',lambda:None,5)
        self.assertIn('OFFLINE regression failure',(self.root/'regression.log').read_text())

    def test_registration_preserves_a_source_snapshot_and_detects_changed_source(self):
        (self.root/'desktop').mkdir();(self.root/'desktop/build_cli.py').write_text('# OFFLINE builder')
        names=[str(self.path.relative_to(self.root)),'desktop/build_cli.py']
        metadata=dict(source=str(self.root),python=sys.executable,files={n:repair.digest((self.root/n).read_bytes()) for n in names})
        db=self.root/'data/tree.sqlite3'
        result=repair.register_source(db,metadata,'OFFLINE-image')
        self.assertEqual(result['state'],'registered')
        snapshot=Path(result['source']);self.assertEqual((snapshot/names[0]).read_text(),self.path.read_text())
        self.path.write_text('# changed after build')
        self.assertEqual(repair.register_source(db,metadata,'OFFLINE-image')['state'],'source_changed')
        self.assertNotEqual((snapshot/names[0]).read_text(),self.path.read_text())


class WorkerTests(fixtures.RecoveryTests):
    # Inherit the real disposable store/broker fixtures, not any production data.
    def prepare_host(self):
        rid=self.request()['repair_id'];row=self.row(rid);data=json.loads(row['payload'])
        source=self.f.db.parent/'source';path=source/repair.SCRIPTS/'parser.py';path.parent.mkdir(parents=True)
        path.write_text('def parse(record):\n    return record["message"].get("content",[])\n')
        metadata=dict(source=str(source),python=sys.executable,files={str(path.relative_to(source)):repair.digest(path.read_bytes())})
        repair.save(source/'.braindance-source.json',metadata)
        repair.save(self.f.db.parent/'monitor/host-repair-installation.json',dict(source=str(source),python=sys.executable,files=metadata['files'],launcher=None,image='OFFLINE-previous'))
        data.update(proof=dict(logs={'error.log':'File "parser.py", line 2, in parse\nAttributeError: str has no get'}),diagnosis=dict(action='needs_host_patch'))
        self.s.recovery.set(rid,'patching',data)
        return rid,source

    def proposal(self,folder,prompt,settings,budget,repo):
        self.assertIn('parser.py',prompt);self.assertEqual(settings['session_budget'],self.config['session_budget'])
        Path(folder).mkdir(parents=True);repair.save(Path(folder)/'usage.json',dict(fixture=True))
        return dict(root_cause='OFFLINE concrete string message',edits=[dict(path=repair.SCRIPTS+'/parser.py',old='return record["message"].get("content",[])',new='return record["message"].get("content",[]) if isinstance(record["message"],dict) else []')])

    def test_detached_worker_checks_every_stage_before_deploy_and_retains_history(self):
        rid,source=self.prepare_host();before=self.s.autopilot.get(self.session['id'])
        stages=[]
        with patch('council.codex_call',side_effect=self.proposal),patch('host_repair.checked',side_effect=lambda command,cwd,folder,name,*args:stages.append(name)),patch('host_repair.deploy',return_value=dict(image='OFFLINE-tested')) as deploy:
            repair.run(self.f.db,rid)
        self.assertEqual(stages,['regression-tests','candidate-build','packaged-check']);deploy.assert_called_once()
        self.assertEqual(self.row(rid)['state'],'awaiting_progress')
        after=self.s.autopilot.get(self.session['id']);self.assertEqual(before['config'],after['config']);self.assertEqual(before['id'],after['id'])
        self.assertNotIn('watchdog_repair_id',after['progress'])
        self.assertNotIn('isinstance', (source/repair.SCRIPTS/'parser.py').read_text())

    def test_rejected_candidate_is_not_deployed_and_does_not_resume_a_paused_session(self):
        rid,source=self.prepare_host()
        with patch('council.codex_call',side_effect=self.proposal),patch('host_repair.checked',side_effect=RuntimeError('OFFLINE tests failed')),patch('host_repair.deploy') as deploy:
            repair.run(self.f.db,rid)
        deploy.assert_not_called();self.assertEqual(self.row(rid)['state'],'needs_attention')
        self.s.autopilot.control(dict(project_id=self.f.project['id'],action='pause'))
        with patch('council.codex_call',side_effect=AssertionError('Paused project cannot spend tokens')),patch('host_repair.deploy') as deploy:
            repair.run(self.f.db,rid)
        deploy.assert_not_called();self.assertEqual(self.row(rid)['state'],'interrupted')
        self.assertEqual(self.s.autopilot.get(self.session['id'])['status'],'paused')


if __name__=='__main__':unittest.main()
