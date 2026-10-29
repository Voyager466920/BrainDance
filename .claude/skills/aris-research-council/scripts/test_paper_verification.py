"""Real subprocess timeout/checkpoint tests with an offline upstream CLI fixture."""
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import council
from paper_verification import run,run_process

FIXTURE='''from dataclasses import dataclass,asdict
import argparse,json,time
from pathlib import Path
DEFAULT_BATCH_SIZE=40
DEFAULT_FUZZY_THRESHOLD=.6
DEFAULT_HALLUCINATION_WARN_THRESHOLD=.2
@dataclass
class PaperInput:
 id:str
 arxiv_id:str|None=None
 doi:str|None=None
 title:str|None=None
@dataclass
class PaperResult:
 id:str
 status:str
 method:str|None=None
 confidence:str|None=None
 reason:str|None=None
 identifiers:dict|None=None
def load_cache(path,ttl):
 return json.loads(path.read_text()) if path.is_file() else {}
def cache_key_for(p):return p.arxiv_id or p.doi or p.title
def verify_papers(papers,cache=None,**kwargs):
 assert all(cache_key_for(p) in cache for p in papers),'Unexpected HTTP path'
 return [PaperResult(id=p.id,**cache[cache_key_for(p)]) for p in papers]
def compute_verdict(results,threshold):
 pending=sum(p.status=='verify_pending' for p in results)
 return ('WARN' if pending else 'PASS'),dict(hallucination_rate=0,pending_rate=pending/len(results),warnings=['transient_failures_present'] if pending else [])
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('--input');a.add_argument('--output');a.add_argument('--cache-dir');args=a.parse_args()
 p=json.loads(Path(args.input).read_text())[0]
 print('UNCOMPRESSED raw fixture '+p['id'],flush=True)
 if p.get('title')=='slow':time.sleep(5)
 result=PaperResult(id='WRONG' if p.get('title')=='bad' else p['id'],status='unverified' if p.get('title')=='negative' else 'verified',method='OFFLINE_FIXTURE')
 Path(args.output).write_text(json.dumps(dict(papers=[asdict(result)])))
'''


class VerificationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.root=self.base/'runs'/'job';self.root.mkdir(parents=True)
        self.work=self.root/'literature';self.work.mkdir();self.aris=self.base/'upstream';(self.aris/'tools').mkdir(parents=True)
        (self.aris/'tools/verify_papers.py').write_text(FIXTURE)
        self.job=dict(aris_repo=str(self.aris));self.events=[]
        from types import SimpleNamespace
        self.progress=SimpleNamespace(emit=lambda phase,message:self.events.append((phase,message)))
    def verify(self,papers,**options):return run(self.job,self.root,self.work,papers,self.progress,per_paper_seconds=.25,total_seconds=2,**options)
    def test_slow_paper_cannot_erase_fast_receipts_or_stop_later_papers(self):
        papers=[dict(id='fast1',title='fast'),dict(id='slow',title='slow'),dict(id='fast2',title='fast')]
        before=time.monotonic();receipt=self.verify(papers)
        self.assertLess(time.monotonic()-before,2)
        self.assertEqual([p['status'] for p in receipt['papers']],['verified','verify_pending','verified'])
        self.assertEqual(receipt['host']['completed'],3);self.assertTrue(all(phase=='verification' for phase,_ in self.events))
        logs=list((self.root/'verification-attempts').rglob('stdout.log'))
        self.assertTrue(any('UNCOMPRESSED raw fixture slow' in p.read_text() for p in logs))
        self.assertEqual(len(list((self.root/'verification-attempts').rglob('checkpoint.json'))),3)
    def test_retry_reuses_completed_and_pending_checkpoints_without_restarting_processes(self):
        papers=[dict(id='fast',title='fast'),dict(id='slow',title='slow')]
        first=self.verify(papers);attempts=list((self.root/'verification-attempts').rglob('attempt.json'))
        with patch('paper_verification.subprocess.Popen',side_effect=AssertionError('No repeat during cooldown')):second=self.verify(papers)
        self.assertEqual(first['papers'],second['papers']);self.assertEqual(len(attempts),2)
        self.assertEqual(len(list((self.root/'verification-attempts').rglob('attempt.json'))),2)
    def test_original_verified_cache_is_used_by_original_function_without_http(self):
        cache=self.base/'paper-verification-cache';cache.mkdir()
        (cache/'verify_papers.json').write_text(json.dumps({'cached':dict(status='verified',method='OFFLINE_CACHED')}))
        with patch('paper_verification.subprocess.Popen',side_effect=AssertionError('Cache hit must not launch HTTP')):receipt=self.verify([dict(id='p1',title='cached')])
        self.assertEqual(receipt['papers'][0]['method'],'OFFLINE_CACHED')
        self.assertTrue(Path(receipt['host']['sources'][0]['receipt']).is_file())
    def test_output_identity_mismatch_cannot_become_a_verified_paper(self):
        result=self.verify([dict(id='p1',title='bad')])['papers'][0]
        self.assertEqual(result['status'],'verify_pending');self.assertIn('invalid_receipt',result['reason'])
    def test_changed_identity_does_not_reuse_the_previous_request_receipt(self):
        self.verify([dict(id='same',doi='doi-one',title='fast')]);self.verify([dict(id='same',doi='doi-two',title='fast')])
        self.assertEqual(len(list((self.root/'verification-attempts').rglob('attempt.json'))),2)
    def test_stop_interrupts_and_cleans_up_the_active_child(self):
        folder=self.work/'cancelled';folder.mkdir();helper=self.aris/'tools/verify_papers.py'
        council.dump(folder/'input.json',[dict(id='slow',title='slow')])
        before=set(council.ACTIVE_PROCESSES)
        with patch('paper_verification.check_active',side_effect=[None,InterruptedError('OFFLINE stop')]):
            with self.assertRaises(InterruptedError):run_process(council.python_command(helper)+['--input',str(folder/'input.json'),'--output',str(folder/'output.json')],folder,self.job,5,self.work)
        self.assertEqual(set(council.ACTIVE_PROCESSES),before);self.assertTrue((folder/'completion.json').is_file())
    def test_total_budget_exhaustion_is_pending_and_does_not_spawn_a_child(self):
        with patch('paper_verification.subprocess.Popen',side_effect=AssertionError('No remaining HTTP budget')):
            result=run(self.job,self.root,self.work,[dict(id='p1',title='slow')],self.progress,total_seconds=0)
        self.assertEqual(result['papers'][0]['status'],'verify_pending')
