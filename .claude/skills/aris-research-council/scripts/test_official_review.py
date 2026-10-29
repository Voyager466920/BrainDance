"""Transport fixtures, plus actual installed upstream helper verification.

No model calls or scientific experiments. The small fixture helper is NOT
production policy; the real upstream helper is exercised separately when present.
"""
import json
from pathlib import Path
import shutil
import tempfile
import unittest

import council
import official_review as review


def fixture_upstream(repo):
    path=Path(repo)/'tools/review_gate.py';path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text('''# OFFLINE transport fixture, not the official ARIS policy
import argparse,json
p=argparse.ArgumentParser()
p.add_argument('--round-backend');p.add_argument('--score',type=float);p.add_argument('--verdict')
a=p.parse_args()
print(json.dumps({'decision':'stop' if a.score>=6 and a.verdict in ('ready','almost') else 'continue','next_backend':'codex'}))
''')
    skill=Path(repo)/'skills/auto-review-loop/SKILL.md'
    skill.parent.mkdir(parents=True,exist_ok=True);skill.write_text('# OFFLINE transport fixture\n- MAX_ROUNDS = 4\n')


def completed_fixture(job,run_ids,number=1,score=7,verdict='almost',run_id='OFFLINE_original_run'):
    """Simulate actual transport outputs; never claim a live Reviewer participated."""
    work=Path(job['native_workspace']);stage=work/'review-stage';stage.mkdir(exist_ok=True)
    for n in range(1,number+1):
        folder=Path(job['run_dir'])/'native-reviewer'/('offline-'+str(n));folder.mkdir(parents=True,exist_ok=True)
        result=dict(score=score,verdict=verdict,review='OFFLINE Reviewer transport fixture')
        council.dump(folder/'usage.json',dict(fixture=True,thread_id='OFFLINE-original-thread'));council.dump(folder/'response.txt',result)
        record=review.record_review(job,dict(review_run_id=run_id,review_round=n),dict(completed_runs=[dict(id=r) for r in run_ids],revision=0),folder,result)
        council.dump(work/'reviewer-latest.json',record)
        review.helper(job,'review_gate.py',['--round-backend','codex','--score',str(score),'--verdict',verdict])
    council.dump(stage/'REVIEW_STATE.json',dict(run_id=run_id,round=number,reviewer_backend='codex',threadId='OFFLINE-original-thread',status='completed',last_score=score,last_verdict=verdict,pending_experiments=[]))
    for name in ['AUTO_REVIEW.md','REVIEWER_MEMORY.md']:(stage/name).write_text('OFFLINE cumulative review fixture')


class OfficialReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name);repo=root/'upstream';fixture_upstream(repo)
        work=root/'work';work.mkdir();shutil.copytree(repo,work/'.aris-official')
        self.job=dict(native_workspace=str(work),run_dir=str(root/'job'),aris_repo=str(repo),auto_session_id='offline-session')
        self.work=work

    def test_negative_first_round_cannot_finish_and_gate_is_authoritative(self):
        completed_fixture(self.job,['r'],score=5,verdict='almost')
        with self.assertRaisesRegex(ValueError,'continue.*1/4'):review.completion(self.job,['r'])
        self.assertFalse((self.work/'native-completion.json').exists())

    def test_score_alone_does_not_override_original_gate(self):
        completed_fixture(self.job,['r'],score=8,verdict='not ready')
        with self.assertRaisesRegex(ValueError,'continue'):review.completion(self.job,['r'])

    def test_positive_and_max_rounds_have_distinct_outcomes(self):
        completed_fixture(self.job,['r'])
        self.assertEqual(review.completion(self.job,['r'])['outcome'],'positive')
        # A new invocation uses its own original run_id, retaining the old records.
        completed_fixture(self.job,['r'],number=4,score=4,verdict='not ready',run_id='OFFLINE_second_run')
        self.assertEqual(review.completion(self.job,['r'])['outcome'],'max_rounds_unresolved')

    def test_resume_uses_same_records_without_dispatch_and_rejects_stale_results(self):
        completed_fixture(self.job,['r'])
        resumed={**self.job,'run_dir':str(Path(self.temp.name)/'resumed')}
        self.assertEqual(review.completion(resumed,['r'])['round'],1)
        with self.assertRaisesRegex(ValueError,'최신 실험'):review.completion(resumed,['r','new-run'])
        with self.assertRaisesRegex(ValueError,'완료되지'):review.completion({**resumed,'native_cycle':1},['r'])

    def test_missing_gate_state_or_fabricated_round_cannot_finish(self):
        completed_fixture(self.job,['r'])
        path=self.work/'review-stage/REVIEW_STATE.json';value=council.read_json(path)
        council.dump(path,{**value,'round':4})
        with self.assertRaisesRegex(ValueError,'round'):review.completion(self.job,['r'])
        council.dump(path,{**value,'status':'in_progress'})
        with self.assertRaisesRegex(ValueError,'Phase E'):review.completion(self.job,['r'])
        council.dump(path,value);(self.work/'native-review-gates.jsonl').unlink()
        with self.assertRaisesRegex(ValueError,'각 결과'):review.completion(self.job,['r'])

    def test_gate_cannot_use_a_different_score_and_changed_helper_is_unavailable(self):
        completed_fixture(self.job,['r'],score=4,verdict='not ready')
        with self.assertRaisesRegex(ValueError,'score/verdict'):
            review.helper(self.job,'review_gate.py',['--round-backend','codex','--score','8','--verdict','ready'])
        (self.work/'.aris-official/tools/review_gate.py').write_text('raise Exception("changed")')
        with self.assertRaisesRegex(ValueError,'REVIEW_UNAVAILABLE'):review.helper(self.job,'review_gate.py',[])

    def test_real_installed_upstream_gate_unchanged(self):
        repo=Path.home()/'aris_repo';original=repo/'tools/review_gate.py'
        if not original.is_file():self.skipTest('Optional local official ARIS checkout is not installed')
        shutil.rmtree(self.work/'.aris-official')
        shutil.copytree(repo/'tools',self.work/'.aris-official/tools',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        shutil.copytree(repo/'skills/auto-review-loop',self.work/'.aris-official/skills/auto-review-loop')
        self.job['aris_repo']=str(repo)
        before=original.read_bytes()
        for score,verdict,expected in [(4,'not ready','continue'),(7,'not ready','continue'),(5,'almost','continue'),(6,'almost','stop')]:
            completed_fixture(self.job,['OFFLINE-measured'],score=score,verdict=verdict,run_id='actual-helper-'+str(score)+verdict)
            if expected=='stop':self.assertEqual(review.completion(self.job,['OFFLINE-measured'])['gate']['decision'],'stop')
            else:
                with self.assertRaisesRegex(ValueError,'continue'):review.completion(self.job,['OFFLINE-measured'])
        completed_fixture(self.job,['OFFLINE-measured'],number=4,score=4,verdict='not ready',run_id='actual-helper-four')
        self.assertEqual(review.completion(self.job,['OFFLINE-measured'])['outcome'],'max_rounds_unresolved')
        self.assertEqual(original.read_bytes(),before)
        self.assertEqual((self.work/'.aris-official/tools/review_gate.py').read_bytes(),before)


if __name__=='__main__':unittest.main()
