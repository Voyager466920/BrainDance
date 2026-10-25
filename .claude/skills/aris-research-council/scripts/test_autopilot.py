"""Durable automatic control against disposable CPU workspaces only."""
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from autopilot import Autopilot
from compute import ComputeSettings
from council import Budget
from experiments import ExperimentEngine
from research import ResearchEngine
from project_cleanup import ProjectCleanup
from tree_store import TreeStore
import steering

FIXTURE=r'''
import json,sys
from pathlib import Path
from unittest.mock import patch
import research_worker
job=json.loads(Path(sys.argv[1]).read_text())
def author(folder,prompt,*args):
 if job['task']=='analyze':return dict(outcome='measured',observations=['actual CPU fixture metrics'],interpretation='infrastructure test only',limitations=[],next_steps=[],next_experiment=dict(decision='continue',title='next comparison',rationale='exercise loop',design='fresh run'))
 code='import os,json\nfrom pathlib import Path\ndef self_test():\n    assert 1+1==2\ndef run_experiment():\n    Path(os.environ["BRAINDANCE_METRICS_PATH"]).write_text(json.dumps({"baseline":{"sum":2},"candidate":{"sum":3}}))\n# '+job['id']
 return dict(ready=True,title='CPU automatic fixture',summary='not scientific evidence',code=code,interpreter='builtin',cwd='',args=[],timeout_seconds=2,metric='sum',direction='maximize',dependencies=[],limitations=[])
def literature(job,root,progress):
 work=root/'literature';work.mkdir();(work/'LITERATURE.md').write_text('OFFLINE literature fixture, not actual search')
 (work/'verified-evidence.json').write_text(json.dumps({'papers':[]}));(root/'literature-usage.json').write_text(json.dumps({'skill_invoked':True,'fixture':True}))
 progress.emit('literature','OFFLINE literature fixture');return work
def council_fixture(args,progress):
 progress('generation','OFFLINE hypothesis fixture');work=Path(args.output);work.mkdir();(work/'status.json').write_text(json.dumps({'status':'completed','fixture':True}))
with patch('research_worker.literature',side_effect=literature),patch('research_worker.verify',side_effect=lambda job,root,work,progress:work/'verified-evidence.json'),patch('research_worker.council.run',side_effect=council_fixture),patch('lab_worker.council.codex_call',side_effect=author),patch('lab_worker.council.claude_call',return_value=dict(verdict='pass',reasons=[])):
 code=research_worker.run(sys.argv[1])
 import time
 time.sleep(.8) # The host must not expose provisional completion before registration.
 sys.exit(code)
'''


class AutomaticTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.store=TreeStore(self.root/'tree.sqlite3');self.node=self.store.add_node(None,'Automatic CPU infrastructure test',kind='problem')
        self.hyp=self.store.add_node(self.node['id'],'Explicit arithmetic fixture',kind='hypothesis')
        self.compute=ComputeSettings(self.root/'compute.json');self.compute.assign(self.node['project_id'],dict(profile_id='local',device_ids=['cpu'],time_budget_minutes=1))
        self.experiments=ExperimentEngine(self.store,self.compute,self.compute.state);self.addCleanup(self.experiments.close)
        self.research=ResearchEngine(self.store,self.experiments);self.addCleanup(self.research.close)
        self.automatic=Autopilot(self.store,self.research,self.experiments,autostart=False);self.addCleanup(self.automatic.close)
        self.script=self.root/'fixture.py'
        self.script.write_text('import sys\nsys.path.insert(0,'+repr(str(Path(__file__).parent))+')\n'+FIXTURE)
        self.research.command=lambda:[sys.executable,'-u',str(self.script)]
        self.research.availability=lambda:dict(available=True,missing=[],aris_repo='/offline-fixture')

    def start(self,**settings):
        return self.automatic.control(dict(project_id=self.node['project_id'],action='start',max_cycles=2,**settings))['session']

    def drive(self,seconds=10):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            item=self.automatic.sessions(self.node['project_id'])[0]
            if item['status']!='running':return item
            try:self.automatic.tick(item)
            except Exception as error:self.fail(str(error))
            time.sleep(.03)
        self.fail('Automatic CPU pipeline did not complete')

    def test_two_cycles_execute_without_per_plan_human_approval_and_analyze_once(self):
        self.start();item=self.drive();self.assertEqual(item['status'],'completed');self.assertEqual(item['progress']['cycles'],2)
        tree=self.store.export_json();runs=tree['experiment_runs'];self.assertEqual(len(runs),2)
        self.assertTrue(all(r['state']=='succeeded' and r['result']['metrics']['candidate']['sum']==3 for r in runs))
        self.assertTrue(all(a['authority'].startswith('automatic:') for a in tree['experiment_approvals']))
        analysis=[j for j in tree['research_jobs'] if j['config'].get('task')=='analyze'];self.assertEqual(len(analysis),2)
        self.assertTrue(all(j['config']['auto_session_id']==item['id'] for j in analysis))
        tasks=[j['config']['task'] for j in tree['research_jobs']]
        self.assertEqual(tasks,['research','analyze','draft','analyze'])
        self.assertTrue(item['progress']['discovery_completed'])
        first=tree['research_jobs'][0];self.assertIsNone(first['config']['reuse_literature'])
        self.assertEqual(first['node_id'],self.node['id'])

    def test_direction_reaches_real_job_context_and_old_plan_is_rejected(self):
        plan=self.experiments.create(dict(node_id=self.hyp['id'],title='old plan',code='print(1)',timeout_seconds=1),provenance=dict(direction_revision=0))
        self.automatic.intervene(dict(node_id=self.hyp['id'],content='Use a new control and report p95.',apply_mode='next'))
        with self.assertRaisesRegex(ValueError,'방향 지시'):self.experiments.approve(plan['id'],plan['digest'],True)
        job=self.research.start(dict(node_id=self.hyp['id'],task='draft',confirm=True))
        self.assertIn('report p95',job['config']['steering']['directions'][-1]['content'])
        direction=self.automatic.state(self.node['project_id'])['directions'][0]
        self.assertEqual(direction['job_id'],job['id']);self.assertEqual(direction['state'],'applied')

    def test_pause_restart_and_target_change_do_not_launch_unattended_work(self):
        item=self.start();self.automatic.control(dict(project_id=self.node['project_id'],action='pause'))
        self.automatic.tick(self.automatic.get(item['id']));self.assertEqual(self.research.list(self.node['project_id'])['jobs'],[])
        self.automatic.control(dict(project_id=self.node['project_id'],action='resume'))
        self.automatic.close();other=Autopilot(self.store,self.research,self.experiments,autostart=False);self.addCleanup(other.close)
        self.assertEqual(other.get(item['id'])['status'],'paused')
        other.control(dict(project_id=self.node['project_id'],action='resume'))
        self.compute.assign(self.node['project_id'],dict(profile_id='local',device_ids=['cpu'],time_budget_minutes=2))
        with self.assertRaisesRegex(ValueError,'변경'):other.tick(other.get(item['id']))
        self.assertEqual(self.research.list(self.node['project_id'])['jobs'],[])

    def test_shared_admission_survives_new_worker_and_keeps_interrupted_reservations(self):
        item=self.start(max_model_calls=3,token_budget=100000);path=item['config']['session_budget']
        cfg=dict(max_model_calls=10,token_budget=1000000,session_budget=path)
        first=Budget(cfg,self.root/'a.json');first.reserve(2,60000)
        second=Budget(cfg,self.root/'b.json')
        with self.assertRaisesRegex(RuntimeError,'토큰'):second.reserve(1,50000)
        second.reserve(1,1000)
        with self.assertRaisesRegex(RuntimeError,'호출'):Budget(cfg,self.root/'c.json').reserve(1,1)
        ledger=json.loads(Path(path).read_text());self.assertEqual(ledger['calls'],3);self.assertEqual(sum(ledger['charges'].values()),61000)

    def test_stop_now_cancels_running_work_and_new_direction_is_next(self):
        item=self.start();self.automatic.tick(item)
        self.automatic.intervene(dict(node_id=self.hyp['id'],content='Change the comparison now.',apply_mode='restart'))
        item=self.automatic.get(item['id']);self.assertEqual(item['progress']['phase'],'prepare');self.assertEqual(item['progress']['preferred_node'],self.hyp['id'])
        self.assertEqual(steering.snapshot(self.store,self.node['project_id'])['directions'][-1]['apply_mode'],'restart')
        self.automatic.control(dict(project_id=self.node['project_id'],action='stop'))
        self.assertEqual(self.automatic.get(item['id'])['status'],'stopped')

    def test_explicit_analyst_stop_prevents_another_experiment(self):
        self.script.write_text(self.script.read_text().replace("decision='continue'","decision='stop'"))
        self.start();item=self.drive()
        self.assertEqual(item['status'],'completed');self.assertEqual(item['progress']['cycles'],1)
        self.assertEqual(len(self.store.export_json()['experiment_runs']),1)

    def test_permanent_project_cleanup_removes_direction_and_session_storage(self):
        item=self.start();folder=Path(item['config']['session_budget']).parent
        self.automatic.intervene(dict(node_id=self.hyp['id'],content='Private operator direction',apply_mode='next'))
        self.automatic.control(dict(project_id=self.node['project_id'],action='stop'))
        self.store.set_project_deleted(self.node['project_id'],True)
        cleanup=ProjectCleanup(self.store,self.experiments,self.compute,self.research)
        cleanup.purge(self.node['project_id'],self.node['title'])
        self.assertFalse(folder.exists())
        with self.store._connect() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM automatic_sessions').fetchone()[0],0)
            self.assertEqual(conn.execute('SELECT count(*) FROM research_directions').fetchone()[0],0)

    def test_resuming_registered_plan_reuses_code_instead_of_repeating_model_authorship(self):
        item=self.start();self.automatic.tick(item);item=self.automatic.get(item['id'])
        deadline=time.monotonic()+4
        while time.monotonic()<deadline:
            job=self.research.get(item['progress']['job_id'])
            if job['state']=='completed':break
            time.sleep(.03)
        self.assertEqual(job['phase'],'experiment_approval')
        self.automatic.save(item,'blocked','A controller interruption after successful registration')
        resumed=self.automatic.control(dict(project_id=self.node['project_id'],action='resume'))['session']
        self.assertEqual(resumed['progress']['phase'],'job');self.assertEqual(resumed['progress']['job_id'],job['id'])
        self.automatic.tick(resumed)
        self.assertEqual(len(self.research.list(self.node['project_id'])['jobs']),1)
        self.assertEqual(len(self.store.export_json()['experiment_runs']),1)

    def test_project_modes_are_independent_and_existing_hypotheses_do_not_skip_discovery(self):
        first=self.start()
        other=self.store.add_node(None,'Second independent project',kind='problem')
        self.store.add_node(other['id'],'Existing second hypothesis',kind='hypothesis')
        self.compute.assign(other['project_id'],dict(profile_id='local',device_ids=['cpu'],time_budget_minutes=1))
        second=self.automatic.control(dict(project_id=other['project_id'],action='start'))['session']
        self.automatic.control(dict(project_id=self.node['project_id'],action='pause'))
        self.assertEqual(self.automatic.get(first['id'])['status'],'paused')
        self.assertEqual(self.automatic.get(second['id'])['status'],'running')
        self.automatic.tick(second)
        job=self.research.get(self.automatic.get(second['id'])['progress']['job_id'])
        self.assertEqual(job['node_id'],other['id']);self.assertEqual(job['config']['task'],'research')
        self.assertIsNone(job['config']['reuse_literature'])
        self.assertNotEqual(first['config']['session_budget'],second['config']['session_budget'])
