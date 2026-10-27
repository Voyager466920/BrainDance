"""Offline independent forward test. No model subprocesses or live DB/config use."""
import argparse, contextlib, copy, io, json, pathlib, sys, tempfile, unittest
from unittest.mock import patch
SCRIPTS=pathlib.Path(__file__).resolve().parent
sys.path.insert(0,str(SCRIPTS))
import council as c
from tree_store import TreeStore

class ForwardTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='aris-independent-'); self.addCleanup(self.tmp.cleanup)
        self.root=pathlib.Path(self.tmp.name)
        self.lit=self.root/'literature.md'; self.lit.write_text('# Synthetic offline fixture\nThese are invented test records, not scientific evidence.')
        self.evidence=self.root/'evidence.json'; self.evidence.write_text(json.dumps([{'arxiv_id':'TEST-ONLY-'+str(i),'title':'Synthetic test record '+str(i),'abstract':'Invented test input for a controlled camera comparison. This is not a real publication. Availability is unknown.','abs_url':'https://example.invalid/fixture/'+str(i),'verification_status':'SYNTHETIC_TEST_ONLY'} for i in range(4)]))
        raw=json.loads(self.evidence.read_text()); self.pid=(raw if isinstance(raw,list) else raw['papers'])[0]['arxiv_id']
        self.cfg={**c.DEFAULTS,**c.MODES['balanced'],'mode':'balanced','coordinator_model':'haiku'}
        self.args=argparse.Namespace(mode='balanced',config=None,output=str(self.root/'out'),db=str(self.root/'tree.sqlite'),resume=False,literature=str(self.lit),evidence=str(self.evidence),node_id=None,topic='VLA camera-shift diagnostic, no GPU',aris_repo='/unused')
        self.proposal={'title':'Offline diagnostic fixture','research_question':'Does camera-shift cause change?', 'hypothesis':'Controlled intervention changes observed actions', 'falsifiable_prediction':'Counterfactual cameras change outcomes','evidence_ids':[self.pid], 'novelty':{'assessment':'unknown','closest_prior_work':self.pid,'uncertainty':'abstract-level'},'feasibility':{'assessment':'planning only','dependencies':[]},'experiment':{'model_dataset_candidates':'unverified','comparison':'paired camera','controls':'fixed seeds','metric':'action shift','rejection_rule':'null effect'},'failure_mode':'confounding'}
        self.root_patch=patch.object(c,'ROOT',self.root); self.root_patch.start(); self.addCleanup(self.root_patch.stop)
    def phases(self,folder,name,*args):
        if name=='generation': return {role:copy.deepcopy(self.proposal) for role in (*c.ROLES,'codex')}
        return {role:{'strongest':'A','weakest':'D','strongest_reason':'fixture','blind_spot':'fixture','collective_miss':'fixture','evaluations':[{'label':letter,'novelty_score':3,'feasibility_score':3,'rigor_score':3,'evidence_ids':[self.pid],'rationale':'offline'} for letter in 'ABCD']} for role in (*c.ROLES,'codex')}
    def chair(self,*args):
        return {'agreement':['offline only'],'clashes':[],'blind_spots':[],'recommendation':'No actual result','first_step':'read original sources','assessments':[{'label':letter,'novelty_score':3,'feasibility_score':3,'rigor_score':3,'priority':50-i,'status':'active','rationale':'offline fixture','evidence_ids':[self.pid]} for i,letter in enumerate('ABCD')]}
    def execute(self,phase=None,chair=None):
        with patch.object(c,'phase',side_effect=phase or self.phases), patch.object(c,'chairman',side_effect=chair or self.chair),contextlib.redirect_stdout(io.StringIO()): c.run(self.args)
    def test_real_evidence_cache_and_lossless_snapshots(self):
        p1,ctx=c.prepare(self.lit,self.evidence,self.root/'first',self.cfg,self.root/'cache')
        p2,ctx2=c.prepare(self.lit,self.evidence,self.root/'second',self.cfg,self.root/'cache')
        self.assertFalse(p1['cache_hit']);self.assertTrue(p2['cache_hit']);self.assertEqual(ctx,ctx2)
        self.assertEqual((self.root/'first/evidence/source-evidence.json').read_bytes(),self.evidence.read_bytes())
        self.assertEqual((self.root/'first/evidence/LITERATURE.md').read_bytes(),self.lit.read_bytes())
        self.assertEqual(len(p1['selected_ids']),4)
    def test_offline_pipeline_then_hold_discard_prioritize(self):
        self.execute();s=TreeStore(self.args.db,max_depth=3);snap=s.export_json();self.assertEqual(len(snap['nodes']),9);self.assertEqual(len(snap['evaluations']),4)
        hyp=next(n for n in snap['nodes'] if n['kind']=='hypothesis');s.update_node(hyp['id'],status='held',priority=99)
        with self.assertRaises(ValueError):s.add_node(hyp['id'],'blocked')
        s.update_node(hyp['id'],status='discarded');self.assertEqual(TreeStore(self.args.db).get_node(hyp['id'])['status'],'discarded')
        s.update_node(hyp['id'],status='active');child=s.add_node(hyp['id'],'Branch design');self.assertEqual(child['depth'],3)
        s.export_json(self.root/'portable.json');self.assertEqual(len(json.loads((self.root/'portable.json').read_text())['evaluations']),4)
    def test_call_preflight_blocks_all_dispatch(self):
        cf=self.root/'tiny.json';cf.write_text(json.dumps({'max_model_calls':10}));self.args.config=str(cf)
        with patch.object(c,'phase',side_effect=AssertionError('dispatch forbidden')):
            with self.assertRaisesRegex(ValueError,'needs 11'):c.run(self.args)
        self.assertEqual(TreeStore(self.args.db).export_json()['nodes'],[])
    def test_resume_missing_run_never_starts_a_new_council(self):
        self.args.resume=True
        with patch.object(c,'phase',side_effect=AssertionError('New dispatch forbidden')):
            with self.assertRaisesRegex(ValueError,'existing run'):c.run(self.args)
        self.assertFalse(pathlib.Path(self.args.output).exists())
    def test_deep_three_rounds_expand_hypotheses_within_depth_four(self):
        self.args.mode='deep'
        config=self.root/'deep.json';config.write_text(json.dumps({'rounds':3}))
        self.args.config=str(config)
        self.execute()
        snapshot=TreeStore(self.args.db).export_json()
        self.assertEqual(len(snapshot['evaluations']),12)
        self.assertEqual(len(snapshot['nodes']),17)
        self.assertEqual(max(n['depth'] for n in snapshot['nodes']),4)
        self.assertTrue((self.root/'out/round-3/COUNCIL_REPORT.md').exists())
    def test_only_declared_source_aliases_are_canonicalized(self):
        raw=json.loads(self.evidence.read_text());raw[0]['id']='p1';self.evidence.write_text(json.dumps(raw))
        pack,_=c.prepare(self.lit,self.evidence,self.root/'aliases',self.cfg,self.root/'cache')
        review={'evaluations':[{'evidence_ids':['p1','INVENTED-SOURCE']} ]}
        c.normalize_evidence_ids(review,pack)
        self.assertEqual(review['evaluations'][0]['evidence_ids'],[self.pid,'INVENTED-SOURCE'])
        self.assertEqual((self.root/'aliases/evidence/source-evidence.json').read_bytes(),self.evidence.read_bytes())

    def test_actual_run_evidence_is_kept_distinct_from_paper_citations(self):
        run_id='123e4567-e89b-12d3-a456-426614174000'
        config=self.root/'results.json';config.write_text(json.dumps(dict(result_evidence_ids=[run_id])));self.args.config=str(config)
        def phases(folder,name,*args):
            result=self.phases(folder,name,*args)
            if name=='peer-review':
                for review in result.values():
                    for item in review['evaluations']:item['evidence_ids'].append(run_id)
            return result
        def chair(*args):
            result=self.chair(*args)
            for item in result['assessments']:item['evidence_ids'].append(run_id)
            return result
        self.execute(phase=phases,chair=chair)
        snapshot=TreeStore(self.args.db).export_json()
        self.assertIn(run_id,json.dumps(snapshot['evaluations']))
        for node in snapshot['nodes']:
            if node['kind']=='hypothesis':self.assertNotIn(run_id,node['evidence'])
        index=json.loads((self.root/'out/result-evidence-index.json').read_text())
        self.assertEqual(index['experiment_run_ids'],[run_id]);self.assertNotIn(run_id,index['paper_ids'])

    def test_review_unknown_evidence_and_invalid_score_rejected_before_chairman(self):
        def broken(folder,name,*args):
            out=self.phases(folder,name,*args)
            if name=='peer-review':
                for item in out.values():
                    for e in item['evaluations']:e['evidence_ids']=['INVENTED-SOURCE'];e['rigor_score']=999
            return out
        with patch.object(c, 'chairman', side_effect=AssertionError('Invalid peer review reached Chairman')) as chairman, patch.object(c, 'phase', side_effect=broken):
            with self.assertRaises(ValueError):
                c.run(self.args)
            chairman.assert_not_called()
        self.assertEqual(TreeStore(self.args.db).export_json()['evaluations'], [])
    def test_resume_rejects_changed_evidence_without_overwriting_frozen_source(self):
        def fail(*args):raise RuntimeError('offline dispatch stop')
        with self.assertRaisesRegex(RuntimeError,'offline dispatch stop'):self.execute(phase=fail)
        original=(self.root/'out/evidence/source-evidence.json').read_bytes()
        data=json.loads(self.evidence.read_text());papers=data if isinstance(data,list) else data['papers'];papers[0]['abstract']='CHANGED ORIGINAL EVIDENCE. This is a replacement.';self.evidence.write_text(json.dumps(data))
        self.args.resume=True
        with self.assertRaises((ValueError, RuntimeError)): self.execute(phase=fail)
        self.assertEqual((self.root/'out/evidence/source-evidence.json').read_bytes(),original)
    def test_completed_run_resume_reuses_without_mutating_artifacts_or_dispatching(self):
        self.execute()
        output = pathlib.Path(self.args.output)
        before = {str(path.relative_to(output)): path.read_bytes() for path in output.rglob('*') if path.is_file()}
        db_before = pathlib.Path(self.args.db).read_bytes()
        self.args.resume = True
        printed = io.StringIO()
        with patch.object(c, 'phase', side_effect=AssertionError('Completed run must not redispatch')), \
             patch.object(c, 'chairman', side_effect=AssertionError('Completed run must not redispatch')), \
             contextlib.redirect_stdout(printed):
            c.run(self.args)
        self.assertTrue(json.loads(printed.getvalue())['reused'])
        self.assertEqual(json.loads((output / 'status.json').read_text())['status'], 'completed')
        after = {str(path.relative_to(output)): path.read_bytes() for path in output.rglob('*') if path.is_file()}
        self.assertEqual(after, before)
        self.assertEqual(pathlib.Path(self.args.db).read_bytes(), db_before)

    def test_anonymization_permutation_all_orders(self):
        proposals={r:copy.deepcopy(self.proposal) for r in (*c.ROLES,'codex')};orders=set()
        for epoch in range(24):
            mapping,blind=c.anonymous(proposals,epoch);self.assertEqual(set(blind),set('ABCD'));orders.add(tuple(mapping))
        self.assertEqual(len(orders),24)

class NativeReceiptTests(unittest.TestCase):
    """Synthetic CLI streams test parsing/accounting only; no real participation."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='aris-receipt-offline-')
        self.addCleanup(self.tmp.cleanup)
        self.folder = pathlib.Path(self.tmp.name) / 'stage'
        self.config = {**c.DEFAULTS, **c.MODES['balanced'], 'coordinator_model': 'haiku'}
        self.budget = c.Budget(self.config, pathlib.Path(self.tmp.name) / 'usage.json')
        self.agents = {'council-novelty': {'description': 'Offline fixture', 'prompt': 'Fixture only', 'model': 'sonnet', 'tools': []}}
        self.final = {'title': 'Actual completed fixture answer', 'evidence_ids': ['paper-1']}
        self.model_usage = {
            'claude-haiku-offline': {'inputTokens': 10, 'outputTokens': 2, 'cacheReadInputTokens': 3, 'cacheCreationInputTokens': 4},
            'claude-sonnet-offline': {'inputTokens': 100, 'outputTokens': 20, 'cacheReadInputTokens': 30, 'cacheCreationInputTokens': 40}}
    def rows(self, status='completed', answer=True):
        result = {'type': 'result', 'subtype': 'success', 'is_error': False, 'result': 'DONE',
                  'session_id': 'offline-session', 'usage': {'input_tokens': 10, 'output_tokens': 2}, 'modelUsage': self.model_usage}
        rows = [
            {'type': 'assistant', 'message': {'model': 'claude-haiku-offline', 'content': [
                {'type': 'tool_use', 'id': 'call-1', 'name': 'Agent', 'input': {'subagent_type': 'council-novelty'}}]}},
            {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': 'call-1', 'content': 'Async agent launched successfully; this is a receipt, not an answer.'}]}},
            copy.deepcopy(result)]
        if answer:
            for text in ('Planning the answer now.', json.dumps({'title': 'Earlier draft', 'evidence_ids': ['paper-1']}), json.dumps(self.final)):
                rows.append({'type': 'assistant', 'parent_tool_use_id': 'call-1', 'message': {
                    'model': 'claude-sonnet-offline', 'content': [{'type': 'text', 'text': text}]}})
        rows.extend([{'type': 'system', 'subtype': 'task_notification', 'tool_use_id': 'call-1', 'status': status},
                     copy.deepcopy(result), copy.deepcopy(result)])
        return rows
    def invoke(self, rows):
        with patch.object(c, 'process', return_value=rows) as process:
            obj = c.claude_call(self.folder, 'generation', 'offline fixture prompt', 'haiku',
                                self.config, self.budget, agents=self.agents, required=('title', 'evidence_ids'))
            process.assert_called_once()
            return obj
    def test_background_answer_last_valid_leaf_and_cumulative_usage_once(self):
        obj = self.invoke(self.rows())
        self.assertEqual(obj, {'novelty': self.final})
        receipt = json.loads((self.folder / 'usage.json').read_text())
        self.assertEqual(receipt['total_tokens'], 209)
        self.assertEqual(receipt['native_agent_calls'][0]['observed_models'], ['claude-sonnet-offline'])
        self.assertEqual(self.budget.observed_tokens, 209)
        self.assertEqual(len(self.budget.records), 1)
        self.assertEqual(self.budget.calls, 2)
        with patch.object(c, 'process', side_effect=AssertionError('Completed receipt must not redispatch')):
            self.assertEqual(c.claude_call(self.folder, 'generation', 'offline fixture prompt', 'haiku',
                                          self.config, self.budget, agents=self.agents, required=('title', 'evidence_ids')), obj)
        self.assertEqual(self.budget.observed_tokens, 209)
    def test_async_launch_receipt_is_never_accepted_as_answer(self):
        with self.assertRaises(ValueError):
            self.invoke(self.rows(answer=False))
        self.assertFalse((self.folder / 'parsed.json').exists())
    def test_incomplete_background_status_rejects_even_valid_json(self):
        with self.assertRaisesRegex(RuntimeError, 'did not complete'):
            self.invoke(self.rows(status='running'))
        self.assertFalse((self.folder / 'parsed.json').exists())
    def test_chairman_response_continuation_reassembles_actual_root_fragments(self):
        answer = {'agreement': ['Evidence supports a test, not a result'],
                  'assessments': [{'label': 'A', 'novelty_score': 3}]}
        whole = json.dumps(answer)
        split = whole.index('novelty_score') + len('nov')
        first, trailing = whole[:split], whole[split:]
        rows = [
            {'type': 'assistant', 'message': {'model': 'claude-sonnet-offline', 'content': [{'type': 'text', 'text': first}]}},
            {'type': 'assistant', 'parent_tool_use_id': 'unrelated-leaf', 'message': {'model': 'claude-sonnet-offline',
                'content': [{'type': 'text', 'text': 'UNRELATED LEAF TEXT MUST NOT ENTER CHAIRMAN JSON'}]}},
            {'type': 'assistant', 'message': {'model': 'claude-sonnet-offline', 'content': [{'type': 'text', 'text': trailing}]}},
            {'type': 'result', 'subtype': 'success', 'result': trailing, 'session_id': 'offline-chairman',
             'usage': {'input_tokens': 10, 'output_tokens': 2}, 'modelUsage': self.model_usage}]
        with patch.object(c, 'process', return_value=rows) as process:
            actual = c.claude_call(self.folder, 'chairman', 'offline continuation fixture', 'sonnet',
                                   self.config, self.budget, required=('agreement', 'assessments'))
        process.assert_called_once()
        self.assertEqual(actual, answer)
        self.assertEqual(json.loads((self.folder / 'parsed.json').read_text()), answer)
        self.assertEqual(self.budget.observed_tokens, 209)

    def test_model_usage_fallback_and_resumed_budget_do_not_double_count(self):
        self.assertEqual(c.claude_tokens({}, {'input_tokens': 5, 'output_tokens': 2, 'cache_read_input_tokens': 7}), 14)
        old = {'model_invocations_reserved': 2, 'observed_tokens': 12, 'records': [
            {'provider': 'anthropic', 'stage_path': 'offline-stage', 'model_usage': self.model_usage,
             'usage': {'input_tokens': 10, 'output_tokens': 2}, 'total_tokens': 12}]}
        c.dump(self.budget.path, old)
        reopened = c.Budget(self.config, self.budget.path)
        self.assertEqual(reopened.observed_tokens, 209)
        reopened.record(copy.deepcopy(reopened.records[0]))
        self.assertEqual(reopened.observed_tokens, 209)
        self.assertEqual(len(reopened.records), 1)

if __name__=='__main__':unittest.main(verbosity=2)
