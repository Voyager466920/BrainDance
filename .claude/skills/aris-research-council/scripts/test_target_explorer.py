import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from target_explorer import query,explore
from test_lab_worker import Progress


class ExplorerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.code=self.root/'research';self.code.mkdir();self.out=self.root/'receipts'
        self.profile=dict(kind='local');self.context=str(self.code)

    def test_inventory_is_fair_across_repositories_and_preserves_actual_sources(self):
        first=self.code/'aaa_vendor';first.mkdir()
        for n in range(80):(first/('module%03d.py'%n)).write_text('X=1')
        target=self.code/'z_actual';target.mkdir();(target/'README.md').write_text('python evaluate.py --config experiment.yaml')
        (target/'evaluate.py').write_text('def evaluate():\n    return "real interface"\n')
        (target/'credentials.py').write_text('PRIVATE_CREDENTIAL')
        inventory=query(self.profile,self.context,dict(op='inventory'),self.out)
        self.assertTrue(any(f['path']=='z_actual/README.md' for f in inventory['files']))
        self.assertNotIn('PRIVATE_CREDENTIAL',json.dumps(inventory))
        result=query(self.profile,self.context,dict(op='read',files=[dict(path='z_actual/evaluate.py')]),self.out)
        self.assertIn('real interface',result['files'][0]['excerpt'])
        self.assertTrue(list(self.out.glob('*.request.json')))

    def test_traversal_symlink_credentials_and_arbitrary_commands_are_denied(self):
        outside=self.root/'private.txt';outside.write_text('PRIVATE')
        (self.code/'link.txt').symlink_to(outside)
        for name in ['../private.txt','link.txt',str(outside),'.ssh/config','credentials.py']:
            with self.assertRaises(ValueError):query(self.profile,self.context,dict(op='read',files=[dict(path=name)]),self.out)
        with self.assertRaises(ValueError):query(self.profile,self.context,dict(op='shell',command='touch bad'),self.out)
        with self.assertRaises(ValueError):query(self.profile,self.context,dict(op='inventory',command='touch bad'),self.out)
        self.assertFalse((self.code/'bad').exists())

    def test_external_metadata_requires_observed_reference_and_never_reads_content(self):
        weight=self.root/'weights.bin';weight.write_bytes(b'PRIVATE_WEIGHT_DATA')
        req=dict(op='stat',paths=[str(weight)])
        with self.assertRaises(ValueError):query(self.profile,self.context,req,self.out)
        result=query(self.profile,self.context,req,self.out,[str(weight)])
        self.assertTrue(result['paths'][0]['exists']);self.assertNotIn('PRIVATE_WEIGHT_DATA',json.dumps(result))
        with self.assertRaises(ValueError):query(self.profile,self.context,dict(op='read',files=[dict(path=str(weight))]),self.out,[str(weight)])

    def test_adaptive_model_requests_are_bounded_cached_and_do_not_execute_code(self):
        source=self.code/'evaluate.py';source.write_text('raise RuntimeError("PROJECT_CODE_MUST_NOT_EXECUTE")')
        inventory=query(self.profile,self.context,dict(op='inventory'),self.out)
        req=dict(op='read',files=[dict(path='evaluate.py')])
        job=dict(context_path=self.context,aris_repo='/offline-fixture');progress=Progress()
        responses=[dict(requests=[req,req],summary='read actual entrypoint'),dict(requests=[],summary='done')]
        with patch('target_explorer.council.codex_call',side_effect=responses):result=explore(job,self.root,progress,self.profile,inventory,{},None,'inspect only')
        self.assertEqual(len(result['additional_reads']),1)
        self.assertIn('PROJECT_CODE_MUST_NOT_EXECUTE',result['additional_reads'][0]['result']['files'][0]['excerpt'])

    def test_model_requests_cannot_turn_themselves_into_external_path_authority(self):
        (self.code/'README.md').write_text('No external paths here.')
        inventory=query(self.profile,self.context,dict(op='inventory'),self.out)
        private=self.root/'unreferenced.txt';private.write_text('not authorized')
        req=dict(op='stat',paths=[str(private)])
        with patch('target_explorer.council.codex_call',side_effect=[dict(requests=[req]),dict(requests=[req])]):
            result=explore(dict(context_path=self.context,aris_repo='/offline'),self.root,Progress(),self.profile,inventory,{},None,'inspect')
        self.assertIn('error',result['additional_reads'][0])

    def test_interpreter_probe_reports_packages_without_running_project_entrypoint(self):
        result=query(self.profile,self.context,dict(op='python',path=sys.executable),self.out,[sys.executable])
        self.assertIn('python_version',result['environment']);self.assertIn('torch',result['environment']['packages'])

    def test_source_referenced_python_is_never_executed_during_inspection(self):
        interpreter=self.code/'.venv/bin/python';interpreter.parent.mkdir(parents=True)
        marker=self.root/'must-not-exist'
        interpreter.write_text('#!/bin/sh\ntouch '+str(marker)+'\n');interpreter.chmod(0o755)
        result=query(self.profile,self.context,dict(op='python',path=str(interpreter)),self.out,[str(interpreter)])
        self.assertIn('filesystem metadata',result['environment']['method']);self.assertFalse(marker.exists())
