"""Scouting interests, source/date deduplication, actual pilot gates and shared reports."""
from datetime import date,timedelta
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import scout
import test_terminal as fixtures
import test_native_pipeline as native_fixtures
from native_pipeline import action,Host


def paper(identity='2601.12345',days=0):
    return dict(id=identity,title='OFFLINE source metadata fixture',published=(date.today()-timedelta(days=days)).isoformat(),abstract='Retained source evidence fixture',abs_url='https://arxiv.org/abs/'+identity)


class ScoutUnitTests(unittest.TestCase):
    def test_auto_time_allocation_uses_remaining_project_budget_and_keeps_fixed_caps(self):
        prefs=scout.validate({})
        allocation=scout.runtime_budget(prefs,{},7200,2,'scout')
        self.assertEqual(allocation['policy'],'auto');self.assertEqual(allocation['max_timeout_seconds'],3600);self.assertEqual(allocation['recommended_timeout_seconds'],900)
        self.assertEqual(scout.runtime_budget(prefs,{},80,2,'scout')['recommended_timeout_seconds'],40)
        self.assertEqual(scout.runtime_budget(prefs,{},0,2,'scout')['max_timeout_seconds'],0)
        self.assertEqual(scout.runtime_budget(prefs,dict(runtime_policy='fixed',pilot_seconds=3),7200,2,'scout')['max_timeout_seconds'],3)

    def test_seed_direction_consistency_and_relative_gain_are_measured(self):
        prefs=scout.validate(dict(style='scout',interests=['classification']))
        def run(a,b,seed_values,direction='maximize'):
            metrics=dict(seeds=[dict(seed=i,baseline={'metric':x},candidate={'metric':y}) for i,(x,y) in enumerate(seed_values)])
            return dict(id='r',state='succeeded',result=dict(metrics=metrics,analysis=dict(status='compared',baseline=a,candidate=b,metric='metric',direction=direction)))
        self.assertTrue(scout.triage(run(.5,.7,[(.5,.7)]*3),prefs)['promising'])
        self.assertTrue(scout.triage(run(10,8,[(10,8)]*3,'minimize'),prefs)['promising'])
        self.assertFalse(scout.triage(run(.5,.51,[(.5,.51)]*3),prefs)['promising'])
        self.assertFalse(scout.triage(run(.5,.7,[(.5,.7)]),prefs)['promising'])
        self.assertFalse(scout.triage(run(0,1,[(0,1)]*3),prefs)['promising'])
        self.assertFalse(scout.triage(run(.5,.9,[(.5,.6)]*3),prefs)['promising'])
        duplicate=run(.5,.7,[(.5,.7)]*3)
        for row in duplicate['result']['metrics']['seeds']:row['seed']=0
        self.assertFalse(scout.triage(duplicate,prefs)['promising'])
        with self.assertRaises(ValueError):scout.validate(dict(style='scout'))
        with self.assertRaises(ValueError):scout.validate(dict(min_improvement=float('nan')))


class ScoutIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.loop=patch('autopilot.Autopilot._loop',return_value=None);self.loop.start();self.addCleanup(self.loop.stop)
        self.fixture=fixtures.TerminalTests('test_source_command_json_does_not_emit_logo_or_color');self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.server=self.fixture.server;self.client=self.fixture.client;self.project=self.fixture.project;self.root=self.client.root(self.project)
        self.prefs=scout.save(self.server.store,self.project['id'],dict(style='scout',interests=['classification'],bridge_fields=['statistics'],pilot_seconds=5,max_pilots=1))
    def test_cli_project_settings_and_app_api_share_project_preferences(self):
        changed=self.fixture.call('interests','--interest','robotics','--interest','systems','--bridge','control','--days','14','--gain','.1')
        self.assertEqual(changed['interests'],['robotics','systems'])
        read=self.client.request('/api/project/research-settings?project_id='+self.project['id'])
        self.assertEqual(changed,read)
        other=self.fixture.call('new','Separate','--goal','Other','--interest','vision','--style','scout')
        isolated=self.client.request('/api/project/research-settings?project_id='+other['project_id'])
        self.assertEqual(isolated['interests'],['vision'])
        self.assertEqual(read['interests'],['robotics','systems'])
    def test_source_dates_duplicate_ids_and_project_isolation(self):
        store=self.server.store;pid=self.project['id']
        rows=scout.accept(store,pid,[paper('2601.12345v1'),paper('2601.12345v2'),paper('2201.00001',2000)],'recent','fixture.json',self.prefs)
        self.assertEqual(len(rows['papers']),1);self.assertEqual(len(rows['already_seen']),1);self.assertEqual(len(rows['excluded']),1)
        old=scout.accept(store,pid,[paper('2201.00001',2000)],'cross-domain','fixture.json',self.prefs)
        self.assertEqual(len(old['papers']),1)
        other=self.fixture.call('new','Separate','--goal','Other')
        self.assertEqual(len(scout.accept(store,other['project_id'],[paper()],'recent','fixture.json',self.prefs)['papers']),1)
    def test_real_source_helper_output_is_retained_and_search_is_cached(self):
        root=Path(self.fixture.temp.name);work=root/'work';work.mkdir();job=dict(db=str(self.fixture.db),project_id=self.project['id'],run_dir=str(work),aris_repo='/upstream-fixture')
        result=subprocess.CompletedProcess([],0,json.dumps([paper()]),'retained stderr fixture')
        with patch('scout.subprocess.run',return_value=result) as call:
            first=scout.search(job,work,dict(query='classification',source='arxiv',kind='recent'))
            second=scout.search(job,work,dict(query='classification',source='arxiv',kind='recent'))
        self.assertEqual(call.call_count,1);self.assertTrue(second['cached']);self.assertEqual(second['papers'],[])
        source=Path(first['source_receipt']).parent
        self.assertEqual((source/'stdout.json').read_text(),result.stdout);self.assertEqual((source/'stderr.log').read_text(),result.stderr)
    def test_scout_start_snapshots_bounds_and_uses_the_native_main(self):
        self.server.research._execute=lambda record:None
        self.server.research.availability=lambda:dict(available=True,missing=[],aris_repo='/offline-fixture')
        state=self.fixture.call('scout','start','--calls','80','--tokens','3000000')['session']
        self.assertEqual(state['config']['research_style'],'scout');self.assertEqual(state['config']['max_cycles'],1)
        self.server.autopilot.tick(state)
        latest=self.server.autopilot.get(state['id']);job=self.server.research.get(latest['progress']['job_id'])
        self.assertEqual(job['config']['task'],'native');self.assertEqual(job['config']['scout_preferences']['pilot_seconds'],5)


class ScoutPilotTests(unittest.TestCase):
    # Reuse the disposable broker fixture without inheriting its test methods.
    call=native_fixtures.NativePipelineTests.call
    wait_run=native_fixtures.NativePipelineTests.wait_run
    fake_review=native_fixtures.NativePipelineTests.fake_review
    def setUp(self):
        native_fixtures.NativePipelineTests.setUp(self)
        self.prefs=scout.save(self.server.store,self.node['project_id'],dict(style='scout',interests=['classification'],bridge_fields=['statistics'],max_pilots=1,pilot_seconds=3,runtime_policy='fixed'))
        self.config.update(research_style='scout',scout_preferences=self.prefs)
        with self.server.store._connect() as conn:conn.execute('UPDATE research_jobs SET config=? WHERE id=?',(json.dumps(self.config),self.job['id']))
        self.host=Host(self.config)
        proof=self.work/'offline-source.json';proof.write_text('{"fixture":true}')
        p=self.work/'scout-source-receipts.json';p.write_text(json.dumps([dict(session_id=self.session['id'],source_receipt=str(proof))]))
        scout.accept(self.server.store,self.node['project_id'],[paper()],'recent','OFFLINE source fixture',self.prefs)
        choice=self.call('scout_candidates',candidate=dict(paper_ids=['arxiv:2601.12345'],interest='classification',mechanism='transfer statistics',hypothesis='OFFLINE classification transport pilot',experiment='paired measured seeds'))
        (self.work/'scout-selection.json').write_text(json.dumps(choice))
    def pilot(self,positive=True):
        b=.7 if positive else .49
        code='import os,json\nfrom pathlib import Path\ndef self_test():\n assert sum([1,2])==3\ndef run_experiment():\n rows=[dict(seed=i,baseline={"accuracy":.5},candidate={"accuracy":'+str(b)+'}) for i in range(3)]\n Path(os.environ["BRAINDANCE_METRICS_PATH"]).write_text(json.dumps(dict(baseline={"accuracy":.5},candidate={"accuracy":'+str(b)+'},seeds=rows)))\n'
        (self.work/'pilot.py').write_text(code)
        with patch('native_pipeline.council.codex_call',side_effect=self.fake_review):run=self.host.execute('experiment',dict(source='pilot.py',title='OFFLINE infrastructure pilot, not scientific results',interpreter='builtin',timeout_seconds=2,metric='accuracy',direction='maximize'))
        receipt=self.wait_run(run['run_id'])
        return run,receipt
    def reviewer(self,run):
        p=Path(self.job['run_dir'])/'native-reviewer/fixture/usage.json';p.parent.mkdir(parents=True,exist_ok=True);p.write_text('{"fixture":true}')
        (self.work/'reviewer-latest.json').write_text(json.dumps(dict(run_ids=[run['run_id']],receipt=str(p))))
    def test_local_report_save_remains_available_after_model_budget_exhaustion(self):
        run,receipt=self.pilot(False);self.reviewer(run)
        trace=Path(self.job['run_dir'])/'native.stdout.jsonl'
        with trace.open('a') as f:
            f.write(json.dumps(dict(type='assistant',message=dict(content=[dict(type='tool_use',id='lit',name='Skill',input=dict(skill='aris-official:research-lit'))])))+'\n')
            f.write(json.dumps(dict(type='user',message=dict(content=[dict(type='tool_result',tool_use_id='lit',content='OFFLINE fixture') ])))+'\n')
        from session_budget import update
        budget=Path(self.config['session_budget']);update(budget,'reserve',key='used',calls=80,estimate=2000000);before=budget.read_bytes()
        (self.work/'report.md').write_text('OFFLINE negative pilot report')
        result=self.host.execute('finish',dict(report='report.md'))
        self.assertEqual(result['promising_count'],0);self.assertEqual(budget.read_bytes(),before)

    def test_pilot_time_limit_cannot_be_increased_by_model_output(self):
        from terminal import ClientError
        (self.work/'too-long.py').write_text('def self_test():\n assert True\ndef run_experiment():\n pass\n')
        with patch('native_pipeline.council.codex_call',side_effect=self.fake_review):
            with self.assertRaisesRegex(ValueError,'시간 한도'):
                self.host.execute('experiment',dict(source='too-long.py',title='Too long fixture',interpreter='builtin',timeout_seconds=4,metric='accuracy',direction='maximize'))
        self.assertEqual(self.call('context')['runs_started'],0)

    def test_auto_allocates_time_before_review_and_supplies_real_deadline_to_cpu_worker(self):
        self.prefs=scout.save(self.server.store,self.node['project_id'],dict(runtime_policy='auto'))
        self.config['scout_preferences']=self.prefs
        with self.server.store._connect() as conn:conn.execute('UPDATE research_jobs SET config=? WHERE id=?',(json.dumps(self.config),self.job['id']))
        code='import os,json,time\nfrom pathlib import Path\nINTERNAL_GUARD_SECONDS=120\ndef self_test():\n assert float(os.environ["BRAINDANCE_TIMEOUT_SECONDS"])>3\n assert float(os.environ["BRAINDANCE_DEADLINE_UNIX"])>time.time()\ndef run_experiment():\n Path(os.environ["BRAINDANCE_METRICS_PATH"]).write_text(json.dumps({"baseline":{"accuracy":.5},"candidate":{"accuracy":.7},"granted_seconds":int(os.environ["BRAINDANCE_TIMEOUT_SECONDS"])}))\n'
        (self.work/'auto.py').write_text(code)
        prompts=[]
        def review(folder,prompt,*args):
            prompts.append(prompt);return self.fake_review(folder,prompt,*args)
        with patch('native_pipeline.council.codex_call',side_effect=review):
            run=self.host.execute('experiment',dict(source='auto.py',title='OFFLINE automatic time allocation',interpreter='builtin',timeout_seconds=3,metric='accuracy',direction='maximize'))
        actual=self.wait_run(run['run_id']);self.assertEqual(actual['state'],'succeeded')
        self.assertEqual(actual['result']['metrics']['granted_seconds'],900)
        self.assertIn('allocated 900 seconds',prompts[0])
        self.assertIn('Do not block solely because an internal time guard differs',prompts[0])
        plan=self.server.experiments.experiment(run['experiment_id'])
        self.assertEqual(plan['spec']['timeout_seconds'],900)
        self.assertEqual(plan['spec']['generation']['runtime_allocation']['policy'],'auto')
        self.assertLess(actual['result']['duration_seconds'],900)

    def test_negative_pilot_finishes_without_heavy_council_or_promising_report(self):
        run,receipt=self.pilot(False);self.reviewer(run)
        report=self.work/'report.md';report.write_text('OFFLINE negative infrastructure pilot')
        result=self.call('finish',report=str(report));self.assertEqual(result['promising_count'],0)
        messages=self.server.chat.messages(self.node['project_id'])['messages']
        self.assertFalse(any(m.get('title','').startswith('탐색 보고 · 유망') for m in messages))
    def test_positive_pilot_requires_result_council_and_reports_in_shared_chat(self):
        run,receipt=self.pilot(True);self.reviewer(run)
        self.assertTrue(self.call('scout_triage')['evaluations'][0]['promising'])
        report=self.work/'report.md';report.write_text('OFFLINE positive infrastructure pilot')
        with self.assertRaisesRegex(ValueError,'Council'):self.call('finish',report=str(report))
        advice=self.work/'council-results-fixture';advice.mkdir();(advice/'status.json').write_text('{"status":"completed","fixture":true}')
        (self.work/'advice-results.json').write_text(json.dumps(dict(path=str(advice),run_ids=[run['run_id']])))
        result=self.call('finish',report=str(report));self.assertEqual(result['promising_count'],1)
        messages=self.server.chat.messages(self.node['project_id'])['messages']
        self.assertTrue(any(m.get('title','').startswith('탐색 보고 · 유망') for m in messages))
