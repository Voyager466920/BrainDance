"""Offline model fixtures plus actual CPU execution; never physical GPU work."""
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from compute import ComputeSettings
from experiments import ExperimentEngine,TERMINAL
from lab_worker import check_code,prepare,analyze,environment
from research import ResearchEngine
from tree_store import TreeStore

CODE='''import json,os
from pathlib import Path
def self_test():
    assert sum([1,2,3])==6
def run_experiment():
    Path(os.environ['BRAINDANCE_METRICS_PATH']).write_text(json.dumps({'baseline':{'sum':3},'candidate':{'sum':6}}))
'''


class Progress:
    def __init__(self):self.events=[]
    def emit(self,*args,**kwargs):self.events.append((args,kwargs))


class LabTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.store=TreeStore(self.root/'tree.sqlite3')
        self.node=self.store.add_node(None,'Offline lab fixture',kind='problem')
        self.hyp=self.store.add_node(self.node['id'],'Explicit test arithmetic fixture',metadata={'experiment':{'metric':'sum'}})
        self.compute=ComputeSettings(self.root/'compute.json');self.compute.assign(self.node['project_id'],dict(profile_id='local',device_ids=['cpu'],time_budget_minutes=1))
        self.exp=ExperimentEngine(self.store,self.compute,self.compute.state);self.addCleanup(self.exp.close)
        self.job=dict(id='offline-fixture',db=self.store.db_path,project_id=self.node['project_id'],node_id=self.hyp['id'],aris_repo='/unused',phase_timeout_seconds=60,context_path='')
        self.work=self.root/'draft';self.work.mkdir();self.progress=Progress()

    def proposal(self):return dict(ready=True,title='Offline arithmetic fixture',summary='Not research evidence',code=CODE,interpreter='builtin',cwd='',args=[],timeout_seconds=5,metric='sum',direction='maximize',dependencies=[],limitations=['offline fixture'])

    def test_actual_environment_probe_reads_reference_files_without_importing_ml(self):
        context=self.root/'reference';context.mkdir();(context/'README.md').write_text('read-only context');(context/'credentials.py').write_text('PRIVATE')
        self.job['context_path']=str(context)
        _,_,inventory=environment(self.job,self.work,self.progress)
        self.assertTrue(inventory['context_exists']);self.assertEqual(inventory['files'][0]['excerpt'],'read-only context')
        self.assertNotIn('PRIVATE',json.dumps(inventory));self.assertIn('torch',inventory['packages'])

    def test_code_contract_refuses_placeholders_and_host_controls_self_test_entrypoint(self):
        final=check_code(CODE);self.assertLess(final.index('    self_test()',final.index('if __name__')),final.index('    run_experiment()',final.index('if __name__')))
        for code in ['print(1)',CODE+'\nif __name__=="__main__":run_experiment()',CODE.replace('assert sum([1,2,3])==6','raise NotImplementedError()'),CODE.replace('assert sum([1,2,3])==6','pass'),CODE.replace('def self_test()', 'async def self_test()')]:
            with self.assertRaises(ValueError):check_code(code)

    def test_human_gpu_number_must_match_the_assigned_uuid_before_code_generation(self):
        state=dict(profiles=[dict(id='local',kind='local')],assignments={self.node['project_id']:dict(profile_id='local',device_ids=['GPU-selected'])})
        inventory=dict(gpus=[dict(index='4',uuid='GPU-selected')])
        self.job['steering']=dict(directions=[dict(content='GPU7에서 실험을 이어가')])
        with patch('lab_worker.ComputeSettings.state',return_value=state),patch('target_explorer.query',return_value=inventory):
            with self.assertRaisesRegex(ValueError,'GPU 번호'):environment(self.job,self.work,self.progress)

    def test_model_authored_plan_is_registered_then_real_cpu_tests_execute_before_metrics(self):
        with patch('lab_worker.council.codex_call',return_value=self.proposal()) as author,patch('lab_worker.council.claude_call',return_value=dict(verdict='pass',reasons=['Offline fixture review'])) as reviewer:
            prepare(self.job,self.work,self.progress)
        self.assertIn('EXACTLY the returned metric string',author.call_args.args[1])
        self.assertIn('host-added __main__',reviewer.call_args.args[2])
        self.assertIn('braindance_self_test',reviewer.call_args.args[2])
        research=ResearchEngine(self.store);self.addCleanup(research.close);research.experiments=self.exp
        result=research._register_generated(dict(id='offline-fixture',run_dir=str(self.work),project_id=self.node['project_id']),dict(state='completed'))
        self.assertEqual(result['phase'],'experiment_approval')
        self.assertEqual(self.exp.list(self.hyp['id'])['experiments'][0]['runs'],[])
        record=json.loads((self.work/'registered-experiment.json').read_text());approval=self.exp.approve(record['id'],record['digest'],True);run=self.exp.enqueue(record['id'],approval['id'])
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            actual=self.exp.run_info(run['id'])
            if actual['state'] in TERMINAL:break
            time.sleep(.03)
        self.assertEqual(actual['state'],'succeeded');self.assertIn('braindance_self_test',actual['stdout_tail'])
        self.assertEqual(actual['result']['metrics']['candidate']['sum'],6)
        self.job['run_id']=run['id'];self.job['node_id']=self.hyp['id']
        with patch('lab_worker.council.codex_call',return_value=dict(outcome='measured',observations=['Actual sum 6'],interpretation='Offline fixture',limitations=[],next_steps=[])):
            analyze(self.job,self.work,self.progress)
        self.assertTrue((self.work/'analysis.json').exists())
        self.assertTrue(any(n['kind']=='analysis' and run['id'] in n['content'] for n in self.store.export_json()['notes']))

    def test_missing_prerequisites_are_recorded_without_creating_fake_executable_plan(self):
        with patch('lab_worker.council.codex_call',return_value=dict(ready=False,blockers=['Missing actual dataset'])):
            self.assertIsNone(prepare(self.job,self.work,self.progress))
        self.assertFalse((self.work/'generated-experiment.json').exists())
        self.assertEqual(self.progress.events[-1][0][0],'blocked')
        self.assertEqual(self.exp.list(self.hyp['id'])['experiments'],[])

    def test_one_bounded_repair_and_no_infinite_model_retry(self):
        bad={**self.proposal(),'code':'not valid python!'}
        with patch('lab_worker.council.codex_call',side_effect=[bad,self.proposal()]) as author,patch('lab_worker.council.claude_call',return_value=dict(verdict='pass',reasons=[])):
            prepare(self.job,self.work,self.progress)
        self.assertEqual(author.call_count,2)
        self.assertTrue((self.work/'generated-experiment.json').exists())

    def test_model_cannot_self_approve_through_public_create_payload(self):
        with self.assertRaises(ValueError):self.exp.create(dict(node_id=self.hyp['id'],title='fake',code=CODE,provenance={'automatic_analysis':True}))
