"""Receipt validation fixtures; no fake claims of real model/agent research."""
import json
from pathlib import Path
import unittest

import council
from official_ideas import validate
import test_native_pipeline as fixtures


class OriginalIdeaTests(unittest.TestCase):
    def setUp(self):
        self.base=fixtures.NativePipelineTests();self.base.setUp();self.addCleanup(self.base.doCleanups)
        self.job=self.base.config;self.work=self.base.work;self.root=Path(self.job['run_dir'])
        p=self.work/'idea-stage/IDEA_REPORT.md';p.parent.mkdir();p.write_text('OFFLINE original-idea artifact fixture')

    def append(self,*events):
        with (self.root/'native.stdout.jsonl').open('a') as out:
            for e in events:out.write(json.dumps(e)+'\n')

    def test_legacy_six_role_receipt_does_not_replace_original_leaf(self):
        council.dump(self.root/'broad-exploration-receipt.json',dict(agents=6,fixture=True))
        with self.assertRaisesRegex(ValueError,'aris-fanout-leaf'):validate(self.job)
        self.assertTrue((self.work/'.claude/agents/aris-fanout-leaf.md').is_file())

    def test_background_leaf_must_really_finish_and_original_codex_receipt_is_needed(self):
        self.append(dict(message=dict(content=[dict(type='tool_use',id='leaf',name='Agent',input=dict(subagent_type='aris-fanout-leaf',run_in_background=True))])),dict(message=dict(content=[dict(type='tool_result',tool_use_id='leaf',content='OFFLINE started ticket')])))
        with self.assertRaisesRegex(ValueError,'실행 중'):validate(self.job)
        self.append(dict(type='system',subtype='task_notification',tool_use_id='leaf',status='completed'))
        with self.assertRaisesRegex(ValueError,'Codex'):validate(self.job)
        p=self.root/'native-reviewer/OFFLINE';p.mkdir(parents=True)
        council.dump(p/'usage.json',dict(fixture=True));(p/'response.txt').write_text('OFFLINE brainstorm fixture')
        result=validate(self.job)
        self.assertEqual(len(result['leaf_calls']),1)
        self.assertEqual(result['leaf_notifications']['leaf'],'completed')


if __name__=='__main__':unittest.main()
