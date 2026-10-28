"""Offline fresh-retrieval/existence/novelty separation; no fabricated live evidence."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import novelty


class NoveltyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.idea=dict(title='OFFLINE fixture',hypothesis='OFFLINE mechanism',novelty_queries=['alternative mechanism','closest prior study','counterexample terminology'])

    def helper(self,repo,name,args,folder,config):
        folder.mkdir(parents=True,exist_ok=True)
        if name=='verify_papers.py':
            self.assertIn('--no-cache',args);rows=json.loads(Path(args[args.index('--input')+1]).read_text())
            output=Path(args[args.index('--output')+1]);output.write_text(json.dumps(dict(papers=[dict(id=p['id'],status='verified',method='OFFLINE') for p in rows])))
            return None
        self.assertNotIn('--year',args);self.assertNotIn('submittedDate',' '.join(args))
        return [dict(id='2601.12345',title='OFFLINE source-returned title',abstract='OFFLINE retrieved abstract',abs_url='https://example.invalid/fixture')]

    def test_fresh_queries_and_no_cache_existence_are_separate_from_novelty(self):
        with patch('novelty.helper',side_effect=self.helper) as helper:
            result=novelty.audit(self.idea,self.root/'first','OFFLINE repo');self.assertEqual(helper.call_count,7)
            self.assertEqual(result['novelty_status'],'unverified');self.assertEqual(len(result['papers']),1)
            novelty.audit(self.idea,self.root/'first','OFFLINE repo');self.assertEqual(helper.call_count,7)
            novelty.audit(self.idea,self.root/'new-cycle','OFFLINE repo');self.assertEqual(helper.call_count,14)
        self.assertTrue((self.root/'first/verification.json').is_file())

    def test_unavailable_sources_and_unverified_ids_never_become_novelty_proof(self):
        with patch('novelty.helper',side_effect=RuntimeError('OFFLINE API outage')):
            result=novelty.audit(self.idea,self.root/'outage','OFFLINE repo')
        self.assertEqual(result['search_status'],'unavailable');self.assertEqual(result['novelty_status'],'unverified');self.assertEqual(result['papers'],[])
        a=novelty.calibrated(dict(novelty_status='plausible_delta',novelty_score=5,closest_prior_work=['INVENTED'],technical_delta='a claim'),result)
        self.assertEqual(a['novelty_status'],'unverified');self.assertEqual(a['novelty_score'],2)

    def test_old_citation_does_not_borrow_verification_without_fresh_retrieval(self):
        with patch('novelty.helper',side_effect=self.helper):
            result=novelty.audit(self.idea,self.root/'cited','OFFLINE repo',cited=[dict(id='2602.12345',title='Prior citation not returned by fresh sources')])
        self.assertEqual(len(result['papers']),1);self.assertEqual(len(result['unverified_papers']),1)
        self.assertIn('not validation of claims',result['papers'][0]['identity_scope'])

    def test_closest_verified_paper_and_concrete_delta_required_for_a_qualified_assessment(self):
        receipt=dict(papers=[dict(id='verified',abstract='OFFLINE source abstract with enough mechanism details to compare the stated idea. '*2)],receipt='OFFLINE receipt')
        good=novelty.calibrated(dict(novelty_status='plausible_delta',closest_prior_work=['verified'],technical_delta='Specific changed mechanism',novelty_score=4),receipt)
        self.assertEqual(good['novelty_status'],'plausible_delta')
        bad=novelty.calibrated(dict(novelty_status='plausible_delta',closest_prior_work=[],technical_delta='',novelty_score=5),receipt)
        self.assertEqual(bad['novelty_status'],'unverified')
