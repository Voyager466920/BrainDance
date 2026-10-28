"""Hypothesis isolation, real concurrent CPU dispatch and durable scheduling.

Model/Skill answers are explicit offline fixtures; these are not scientific results.
"""
import json
from pathlib import Path
import time
import unittest
from unittest.mock import patch

from native_pipeline import Host,install,SKILLS,action
from research_tasks import stage,tick,listing,update,slots,control
import test_native_pipeline as fixtures


class ResearchTaskTests(unittest.TestCase):
    def setUp(self):
        self.base=fixtures.NativePipelineTests();self.base.setUp();self.addCleanup(self.base.doCleanups)
        self.server=self.base.server;self.pid=self.base.node['project_id'];self.controller=self.server.autopilot
        self.controller.control(dict(project_id=self.pid,action='stop'))
        with self.server.store._connect() as c:c.execute("UPDATE research_jobs SET state='cancelled' WHERE project_id=?",(self.pid,))
        self.server.research.active_id=None
        self.server.compute.assign(self.pid,dict(profile_id='local',device_ids=['cpu'],time_budget_minutes=1,max_parallel_runs=2,auto_run=False))
        self.item=self.controller.control(dict(project_id=self.pid,action='start',execution_policy='until_deadline',duration_seconds=60,orchestration='hypothesis-tasks'))['session']
        self.controller.native_tick(self.item);self.item=self.controller.get(self.item['id']);discovery=self.server.research.get(self.item['progress']['job_id'])
        self.nodes=[self.server.store.add_node(self.base.node['id'],'OFFLINE hypothesis '+str(i),kind='hypothesis',metadata=dict(rating_basis='OFFLINE evidence only',research_ratings=dict(potential=60,novelty_provisional=40,feasibility=80,falsifiability=80),scout_cycle=0,novelty_recheck=dict(novelty_status='unverified'))) for i in range(2)]
        self.tasks=stage(self.server,discovery,self.item,[n['id'] for n in self.nodes])
        with self.server.store._connect() as c:c.execute("UPDATE research_jobs SET state='completed',phase='native-completed' WHERE id=?",(discovery['id'],))
        self.server.research.active_id=None;self.controller.save(self.item,phase='tasks',job_id=None)
        tick(self.controller,self.item);self.tasks=listing(self.server.store,self.item['id'])
        self.jobs=[self.server.research.get(t['job_id']) for t in self.tasks];self.hosts=[]
        for job in self.jobs:
            install(job['config']);rows=[]
            for i,skill in enumerate(SKILLS):rows.extend([dict(type='assistant',message=dict(content=[dict(type='tool_use',id=str(i),name='Skill',input=dict(skill='aris-official:'+skill))])),dict(type='user',message=dict(content=[dict(type='tool_result',tool_use_id=str(i),content='OFFLINE fixture')]))])
            (Path(job['run_dir'])/'native.stdout.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows));self.hosts.append(Host(job['config']))

    def execute(self,index,seconds=.6):
        work=Path(self.jobs[index]['config']['native_workspace'])
        (work/'pilot.py').write_text('import time,json,os\nfrom pathlib import Path\ndef self_test():\n assert 1+1==2\ndef run_experiment():\n time.sleep('+str(seconds)+')\n Path(os.environ["BRAINDANCE_METRICS_PATH"]).write_text(json.dumps({"baseline":{"metric":1},"candidate":{"metric":2}}))\n')
        with patch('native_pipeline.council.codex_call',side_effect=self.base.fake_review):return self.hosts[index].execute('experiment',dict(source='pilot.py',title='OFFLINE CPU task '+str(index),timeout_seconds=4,metric='metric'))

    def wait(self,identity):
        end=time.monotonic()+8
        while time.monotonic()<end:
            run=self.server.experiments.run_info(identity)
            if run['state'] not in {'queued','running'}:return run
            time.sleep(.03)
        self.fail('CPU fixture did not finish')

    def test_tasks_have_separate_original_workspaces_and_receipts_and_share_project_conversation(self):
        self.assertEqual(len(self.tasks),2);self.assertEqual(len({j['config']['native_workspace'] for j in self.jobs}),2)
        self.assertEqual(len({j['config']['project_session']['id'] for j in self.jobs}),1)
        first=self.execute(0);second=self.execute(1);a=self.wait(first['run_id']);b=self.wait(second['run_id'])
        self.assertEqual(a['state'],'succeeded');self.assertEqual(b['state'],'succeeded')
        self.assertLess(a['started_at'],b['finished_at']);self.assertLess(b['started_at'],a['finished_at'])
        self.assertEqual(len(self.hosts[0].execute('context',{})['completed_runs']),1)
        with self.assertRaises(ValueError):action(self.server,dict(job_id=self.jobs[0]['id'],action='receipt',run_id=second['run_id']))
        for job in self.jobs:
            work=Path(job['config']['native_workspace'])
            for name in SKILLS:self.assertEqual((work/'.aris-official/skills'/name/'SKILL.md').read_bytes(),(self.base.aris/'skills'/name/'SKILL.md').read_bytes())

    def test_one_task_can_stop_while_other_study_continues(self):
        a=self.execute(0,3);b=self.execute(1,.7)
        control(self.server,self.pid,self.tasks[0]['id'],'stop')
        self.assertEqual(self.wait(a['run_id'])['state'],'cancelled');self.assertEqual(self.wait(b['run_id'])['state'],'succeeded')
        self.assertEqual(listing(self.server.store,self.item['id'])[0]['state'],'stopped')

    def test_completion_starts_new_discovery_without_resetting_deadline_or_ledger(self):
        ledger=Path(self.item['config']['session_budget']);before=ledger.read_bytes();end=self.item['config']['deadline_epoch']
        for task in self.tasks:update(self.server.store,task['id'],state='completed')
        tick(self.controller,self.item);after=self.controller.get(self.item['id'])
        self.assertEqual(after['status'],'running');self.assertEqual(after['progress']['phase'],'prepare');self.assertEqual(after['progress']['native_cycle'],1)
        self.assertEqual(after['config']['deadline_epoch'],end);self.assertEqual(ledger.read_bytes(),before)

    def test_selected_gpu_slots_are_exclusive_and_fall_back_to_sequential(self):
        self.assertEqual(slots(dict(device_ids=['GPU-4'],max_parallel_runs=6)),[['GPU-4']])
        self.assertEqual(slots(dict(device_ids=['GPU-4','GPU-5'],max_parallel_runs=2)),[['GPU-4'],['GPU-5']])
