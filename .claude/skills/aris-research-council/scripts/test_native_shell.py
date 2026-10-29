"""Original helper access without untracked research or GPU shell execution."""
import json
from pathlib import Path
import shlex
import tempfile
import unittest

from native_shell import decide


class NativeShellTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name);self.work=root/'work';self.work.mkdir();repo=root/'official';(repo/'tools').mkdir(parents=True)
        (repo/'tools/review_gate.py').write_text('# OFFLINE canonical helper fixture')
        self.job=dict(native_workspace=str(self.work),aris_repo=str(repo),run_dir=str(root/'job'))
        (self.work/'.aris').mkdir();(self.work/'.aris/tools').symlink_to(repo/'tools')

    def call(self,command):return decide(self.job,dict(tool_name='Bash',tool_input=dict(command=command)))['hookSpecificOutput']

    def test_local_bookkeeping_and_exact_original_helper_are_available(self):
        self.assertEqual(self.call('mkdir -p idea-stage')['permissionDecision'],'allow')
        result=self.call('python3 .aris/tools/review_gate.py --round-backend codex --score 4 --verdict "not ready"')
        self.assertEqual(result['permissionDecision'],'allow')
        argv=shlex.split(result['updatedInput']['command']);request=Path(argv[-1])
        self.assertEqual(json.loads(request.read_text())['args'][-1],'not ready')
        other=self.call('python3 .aris/tools/review_gate.py --round-backend codex --score 5 --verdict almost')
        self.assertNotEqual(request,Path(shlex.split(other['updatedInput']['command'])[-1]))

    def test_gpu_ssh_inline_python_and_workspace_escape_use_existing_broker(self):
        for command in ['ssh gpu-host python experiment.py','python3 experiment.py','python3 -c "import torch"','mkdir ../outside','cat ~/.ssh/config','mkdir idea-stage; python experiment.py']:
            self.assertEqual(self.call(command)['permissionDecision'],'deny',command)


if __name__=='__main__':unittest.main()
