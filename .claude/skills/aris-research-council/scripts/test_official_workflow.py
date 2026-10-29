"""Canonical artifacts cannot be replaced by an invocation or a prose claim."""
from pathlib import Path
import tempfile
import unittest
from official_workflow import completed,plans,ARTIFACTS
from test_official_review import discovery_fixture


class WorkflowEvidenceTests(unittest.TestCase):
    def test_missing_refinement_or_actual_gate_blocks_completion(self):
        with tempfile.TemporaryDirectory() as folder:
            work=Path(folder)/'work';work.mkdir();job=dict(native_workspace=str(work),run_dir=str(Path(folder)/'job'))
            with self.assertRaisesRegex(ValueError,'FINAL_PROPOSAL'):plans(job)
            discovery_fixture(job);self.assertEqual(completed(job)['artifacts'],list(ARTIFACTS))
            (work/'refine-logs/FINAL_PROPOSAL.md').write_text('Changed after upstream gate')
            with self.assertRaisesRegex(ValueError,'다시 실행'):completed(job)
            discovery_fixture(job)
            (work/'refine-logs/EXPERIMENT_PLAN.md').unlink()
            with self.assertRaisesRegex(ValueError,'EXPERIMENT_PLAN'):completed(job)
            discovery_fixture(job);(work/'native-discovery-gate.json').unlink()
            with self.assertRaisesRegex(ValueError,'실제 실행'):completed(job)


if __name__=='__main__':unittest.main()
