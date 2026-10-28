"""Offline six-lens exploration and score validation; no paid models."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import council
import exploration


class ExplorationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.work=self.root/'work';self.work.mkdir()
        self.paper=dict(id='OFFLINE-ONLY',title='Synthetic fixture, not a publication',abstract='Controlled evidence fixture. Not a real scientific source.',url='https://example.invalid',verification_status='SYNTHETIC_TEST_ONLY')
        (self.work/'LITERATURE.md').write_text('OFFLINE synthetic fixture');(self.work/'source-evidence.json').write_text(json.dumps(dict(papers=[self.paper])));(self.work/'candidate_papers.json').write_text('[]')
        self.cfg={**council.DEFAULTS,**council.MODES['balanced']}
        self.job=dict(topic='OFFLINE research direction',db=str(self.root/'tree.sqlite3'))

    def verify(self,job,root,source,progress):
        p=source/'verified-evidence.json';p.write_text(json.dumps(dict(papers=[self.paper])));return p

    def call(self,folder,name,prompt,model,cfg,budget,agents=None,required=()):
        self.agents.update(agents)
        return {role:dict(title='OFFLINE '+role,evidence_ids=['OFFLINE-ONLY'],ratings=dict(potential=60,novelty_provisional=40,feasibility=70,falsifiability=80)) for role in agents}

    def test_six_distinct_isolated_lenses_and_cheaper_models_for_routine_roles(self):
        self.agents={}
        with patch('research_worker.verify',side_effect=self.verify),patch('council.claude_call',side_effect=self.call):result=exploration.run(self.job,self.root,self.work,self.cfg)
        self.assertEqual(len(self.agents),6);self.assertEqual(result['exploration_agents'],6)
        self.assertEqual({v['prompt'].splitlines()[0] for v in self.agents.values()}.__len__(),6)
        self.assertTrue(all(v['tools']==[] for v in self.agents.values()))
        self.assertEqual(self.agents['explore-trends']['model'],'haiku');self.assertEqual(self.agents['explore-principles']['model'],'sonnet')
        self.assertTrue((self.root/'broad-exploration-receipt.json').is_file())

    def test_invalid_numeric_ratings_are_rejected(self):
        self.agents={}
        def bad(*args,**kwargs):
            output=self.call(*args,**kwargs)
            for p in output.values():p['ratings']['potential']=101
            return output
        with patch('research_worker.verify',side_effect=self.verify),patch('council.claude_call',side_effect=bad):
            with self.assertRaisesRegex(ValueError,'0–100'):exploration.run(self.job,self.root,self.work,self.cfg)
