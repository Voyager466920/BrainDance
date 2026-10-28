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

    def test_economy_preserves_six_roles_and_reduces_context_before_preparation(self):
        from collections import Counter
        self.agents={};self.job['cost_profile']='economy'
        with patch('research_worker.verify',side_effect=self.verify),patch('council.claude_call',side_effect=self.call),patch('council.prepare',wraps=council.prepare) as prepare:
            exploration.run(self.job,self.root,self.work,self.cfg)
            settings=prepare.call_args.args[3];self.assertEqual(settings['context_chars'],12000);self.assertGreaterEqual(settings['output_tokens'],6000)
        self.assertEqual(Counter(v['model'] for v in self.agents.values()),{'haiku':4,'sonnet':2})
        self.assertTrue(all('exactly ONE compact JSON' in v['prompt'] and 'at most 900 output tokens' in v['prompt'] for v in self.agents.values()))
        self.assertTrue(all('OUTPUT_SCHEMA' in v['prompt'] and 'ratings.feasibility' in v['prompt'] for v in self.agents.values()))

    def test_closed_invalid_wave_gets_new_attempt_but_partial_call_is_not_replayed(self):
        base=self.root/'wave-trends';base.mkdir();log=base/'exploration.stdout.jsonl'
        log.write_text(json.dumps(dict(type='assistant',message=dict(content=[])))+'\n')
        self.assertEqual(exploration.wave_attempt(base)[0],base)
        log.write_text(log.read_text()+json.dumps(dict(type='result',subtype='success',result='DONE but Agent JSON failed'))+'\n')
        raw=log.read_bytes();folder,attempt=exploration.wave_attempt(base)
        self.assertNotEqual(folder,base);self.assertEqual(attempt,1);self.assertEqual(log.read_bytes(),raw)
        folder.mkdir();(folder/'parsed.json').write_text('{}');(folder/'usage.json').write_text('{}')
        self.assertEqual(exploration.wave_attempt(base),(folder,1))
