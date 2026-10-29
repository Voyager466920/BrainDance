"""Synthetic account allowances and actual CPU cancellation; no paid model/GPU calls."""
import copy
import json
from pathlib import Path
import time
import unittest
from unittest.mock import patch

import quota_guard as q
import test_terminal as fixtures
import test_native_pipeline as native
from session_budget import update,QuotaStopped
from tree_store import now


def status(gpt=50,claude=80):
    return dict(providers=[dict(name=name,connection='connected',usage_state='available',checked_at=now(),windows=[dict(minutes=300,used_percent=100-left,resets_at=2000000000),dict(minutes=10080,used_percent=10,resets_at=2000100000)]) for name,left in [('GPT',gpt),('Claude',claude)]])


class QuotaMathTests(unittest.TestCase):
    def test_twenty_percentage_points_not_twenty_percent_of_start(self):
        guard=q.capture(status(50,80),20)
        self.assertFalse(q.evaluate(guard,q.snapshot(status(31,61)))['stop'])
        decision=q.evaluate(guard,q.snapshot(status(30,61)))
        self.assertTrue(decision['stop']);self.assertEqual(decision['stop_at'],30)
        decision=q.evaluate(guard,q.snapshot(status(31,60)));self.assertEqual(decision['provider'],'Claude');self.assertEqual(decision['stop_at'],60)
        self.assertIn('시작 50% → 중지 30%',q.describe(q.snapshot(status(30,61)),guard))

    def test_weekly_window_and_resets_keep_original_start_line(self):
        guard=q.capture(status(),20);current=status(99,99)
        self.assertFalse(q.evaluate(guard,q.snapshot(current))['stop'])
        current['providers'][1]['windows'][1].update(used_percent=30,resets_at=3000000000)
        self.assertTrue(q.evaluate(guard,q.snapshot(current))['stop'])
        self.assertEqual(guard['baseline']['providers'][0]['windows'][0]['remaining_percent'],50)

    def test_unknown_stale_missing_and_exhausted_usage_never_look_safe(self):
        guard=q.capture(status(),20)
        for raw in [dict(providers=[]),status()]:
            if raw['providers']:raw['providers'][0]['checked_at']='2000-01-01T00:00:00+00:00'
            with self.assertRaises(ValueError):q.capture(raw,20)
            self.assertTrue(q.evaluate(guard,q.snapshot(raw))['stop'])
        missing=status();missing['providers'][0]['windows']=missing['providers'][0]['windows'][1:]
        self.assertTrue(q.evaluate(guard,q.snapshot(missing))['stop'])
        with self.assertRaises(ValueError):q.capture(status(0,80),20)
        for amount in [True,0,-1,101,20.0]:
            with self.assertRaises(ValueError):q.capture(status(),amount)


class QuotaControllerTests(unittest.TestCase):
    setUp=fixtures.TerminalTests.setUp
    close_server=fixtures.TerminalTests.close_server
    def start(self):
        self.server.autopilot.quota_status=lambda force=False:status()
        return self.server.autopilot.control(dict(project_id=self.project['id'],action='start',duration_seconds=3600,execution_policy='until_deadline',quota_drop_percent=20))['session']
    def test_capture_persists_and_stop_blocks_future_reservations_without_reset(self):
        item=self.start();ledger=Path(item['config']['session_budget']);deadline=item['config']['deadline_epoch']
        update(ledger,'reserve',key='already used',calls=1,estimate=100)
        self.server.autopilot.quota_status=lambda force=False:status(30,70)
        self.server.autopilot.tick(item)
        actual=self.server.autopilot.get(item['id']);self.assertEqual(actual['status'],'stopped')
        self.assertEqual(actual['config']['deadline_epoch'],deadline);self.assertEqual(actual['progress']['quota_stop']['stop_at'],30)
        raw=json.loads(ledger.read_text());self.assertEqual(raw['calls'],1);self.assertEqual(raw['charges']['already used'],100)
        with self.assertRaises(QuotaStopped):update(ledger,'reserve',key='forbidden',calls=1,estimate=1)
        update(ledger,'record',key='late receipt',tokens=42)
        self.assertEqual(json.loads(ledger.read_text())['observed']['late receipt'],42)
        message=self.server.chat.send(dict(node_id=self.client.root(self.project)['id'],content='정리만 해줘',mode='ask',request_id='quota-ended-summary-001'))
        context=self.server.chat.context(message);self.assertTrue(context['reply_policy']['independent_from_research_deadline']);self.assertEqual(context['actual_session']['id'],item['id'])

    def test_cli_start_option_reaches_the_same_authoritative_start_policy(self):
        from terminal import dispatch,parser
        self.server.autopilot.quota_status=lambda force=False:status()
        result=dispatch(self.client,parser().parse_args(['auto','start','--hours','1','--quota-drop-percent','20']),self.project)
        guard=result['session']['config']['quota_guard']
        self.assertEqual(guard['drop_percent'],20);self.assertEqual(guard['baseline']['providers'][0]['windows'][0]['remaining_percent'],50)

    def test_missing_start_usage_rejects_before_creating_an_automatic_session(self):
        self.server.autopilot.quota_status=lambda force=False:dict(providers=[])
        with self.assertRaises(ValueError):self.server.autopilot.control(dict(project_id=self.project['id'],action='start',quota_drop_percent=20))
        self.assertFalse(self.server.autopilot.sessions(self.project['id']))

    def test_result_and_remaining_usage_have_the_same_order_in_slack_and_markdown(self):
        from research_reports import project_data,build_report,result_status,signature
        from slack_notifications import message_for
        item=self.start();self.server.autopilot.quota_status=lambda force=False:status(30,70);self.server.autopilot.tick(item)
        self.server.publications.tick()
        with self.server.publications.connect() as c:local=c.execute("SELECT count(*) FROM jobs WHERE project_id=? AND kind='local'",(self.project['id'],)).fetchone()[0]
        self.assertEqual(local,1)
        data=project_data(self.server.store,self.project['id']);self.assertEqual(result_status(data),'탐색중')
        data['brief']=dict(findings='실험 전에 중지한 실제 상태')
        message=message_for(data)['text'];self.assertTrue(message.startswith('*결과: 탐색중*'))
        self.assertLess(message.index('*상세 결과*'),message.index('*남은 사용량*'));self.assertIn('5시간 잔여 30%',message)
        report=build_report(Path(self.temp.name)/'reports',data)
        self.assertEqual([s[0] for s in report['sections']][:3],['결과','상세 결과','남은 사용량'])
        changed=copy.deepcopy(data);changed['account_usage']=q.snapshot(status(29,69));self.assertEqual(signature(data),signature(changed))
        changed['execution_state']['status']='running';self.assertNotEqual(signature(data),signature(changed))

    def test_execution_success_without_a_comparison_is_not_a_claim_of_improvement(self):
        from research_reports import result_status
        data=dict(runs=[dict(state='succeeded',direction='minimize',analysis=dict(status='compared',baseline=100,candidate=80))])
        self.assertEqual(result_status(data),'탐색중')
        data['runs'][0]['analysis']['candidate']=120;self.assertEqual(result_status(data),'실패')
        data['runs'][0]['analysis']=dict(status='measured',value=80);self.assertEqual(result_status(data),'탐색중')
        data['study_outcome']='rejected';self.assertEqual(result_status(data),'실패')


class QuotaCPUCancellationTests(unittest.TestCase):
    setUp=native.NativePipelineTests.setUp
    call=native.NativePipelineTests.call
    wait_run=native.NativePipelineTests.wait_run
    fake_review=native.NativePipelineTests.fake_review
    def test_threshold_cancels_actual_cpu_work_and_saves_partial_results(self):
        self.server.autopilot.control(dict(project_id=self.node['project_id'],action='time_only',duration_seconds=60))
        guard=q.capture(status(),20)
        item=self.server.autopilot.get(self.session['id']);item['config']['quota_guard']=guard
        with self.server.store._connect() as c:c.execute('UPDATE automatic_sessions SET config=? WHERE id=?',(json.dumps(item['config']),item['id']))
        self.server.autopilot.quota_status=lambda force=False:status()
        (self.work/'advice-ideas.json').write_text('{}')
        (self.work/'long.py').write_text('import time\ndef self_test():\n assert True\ndef run_experiment():\n print("QUOTA_CPU_STARTED",flush=True)\n time.sleep(30)\n')
        with patch('native_pipeline.council.codex_call',side_effect=self.fake_review):run=self.host.execute('experiment',dict(source='long.py',title='OFFLINE quota cancellation',timeout_seconds=20))
        end=time.monotonic()+3
        while time.monotonic()<end:
            if 'QUOTA_CPU_STARTED' in self.server.experiments.run_info(run['run_id'])['stdout_tail']:break
            time.sleep(.03)
        self.server.autopilot.quota_status=lambda force=False:status(30,70)
        self.assertFalse(self.server.autopilot.check_quota(self.server.autopilot.get(item['id']),force=True))
        end=time.monotonic()+4
        while time.monotonic()<end:
            record=self.server.experiments.run_info(run['run_id'])
            if record['state'] not in {'queued','running'}:break
            time.sleep(.03)
        self.assertEqual(record['state'],'cancelled');self.assertIn('QUOTA_CPU_STARTED',record['stdout_tail'])
        self.assertEqual(self.server.autopilot.get(item['id'])['status'],'stopped')
