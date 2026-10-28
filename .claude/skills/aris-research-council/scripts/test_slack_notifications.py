"""Offline personal-DM protocol fixture; never sends real Slack messages."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import os
import io
import subprocess
import sys
import terminal
from tree_store import now

from slack_notifications import SlackAPI,SlackError,SlackNotifications,message_for
import test_terminal as fixtures

TOKEN='xoxb-OFFLINE-fixture-not-a-live-secret'
MEMBER='U0123456789'
DM='D0123456789'

class SlackNotificationTests(unittest.TestCase):
    def setUp(self):
        stop=patch('slack_notifications.SlackNotifications.loop',return_value=None);stop.start();self.addCleanup(stop.stop)
        self.fixture=fixtures.TerminalTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.server=self.fixture.server;self.client=self.fixture.client;self.pid=self.fixture.project['id'];self.service=self.server.notifications;self.sent=[]
        def request(api,method,payload=None):
            if method=='auth.test':return dict(ok=True,team='OFFLINE workspace',team_id='T0123456789',user_id='U9999999999')
            if method=='conversations.open':self.assertEqual(payload,dict(users=MEMBER));return dict(ok=True,channel=dict(id=DM))
            if method=='chat.postMessage':self.sent.append(payload);self.assertEqual(payload['channel'],DM);return dict(ok=True,ts='1234567890.123456')
            self.fail(method)
        mock=patch.object(SlackAPI,'request',autospec=True,side_effect=request);mock.start();self.addCleanup(mock.stop)
    def setup(self):return self.client.request('/api/slack/configure',dict(project_id=self.pid,member_id=MEMBER,token=TOKEN,enabled=True))
    def row(self,id):
        with self.service.connect() as c:return dict(c.execute('SELECT * FROM deliveries WHERE id=?',(id,)).fetchone())
    def completed_study(self,identity,project,finished_at=None,role='hypothesis'):
        folder=Path(self.server.store.db_path).parent/'council-runs'/identity;folder.mkdir(parents=True)
        (folder/'native-completion.json').write_text(json.dumps(dict(job_id=identity,run_ids=[])))
        (folder/'research-brief.json').write_text(json.dumps(dict(problem='OFFLINE fixture',approach='No real model or experiment',findings='OFFLINE result')))
        finished_at=finished_at or now();node=self.client.root(project)
        with self.server.store._connect() as c:c.execute('INSERT INTO research_jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(identity,project['id'],node['id'],'OFFLINE study','completed','native-completed','OFFLINE fixture','lite',json.dumps(dict(task_role=role)),str(folder),finished_at,finished_at,finished_at,None))
    def test_quota_stop_reports_once_with_outcome_first_and_remaining_allowance(self):
        from test_quota_guard import status
        self.setup();controller=self.server.autopilot
        controller.quota_status=lambda force=False:status()
        item=controller.control(dict(project_id=self.pid,action='start',execution_policy='until_deadline',duration_seconds=3600,quota_drop_percent=20))['session']
        controller.quota_status=lambda force=False:status(30,70);self.service.quota_snapshot=lambda:status(30,70)
        controller.tick(item);self.service.tick();self.service.tick()
        with self.service.connect() as c:rows=c.execute("SELECT id FROM deliveries WHERE event_key LIKE 'session:%'").fetchall()
        self.assertEqual(len(rows),1);self.service.process(self.row(rows[0]['id']))
        text=self.sent[0]['text'];self.assertTrue(text.startswith('*결과: 탐색중*'))
        self.assertIn('GPT: 5시간 잔여 30%',text);self.assertIn('시작 50% → 중지 30%',text)
        self.assertLess(text.index('*상세 결과*'),text.index('*남은 사용량*'))

    def test_personal_dm_setup_keeps_secret_local_and_does_not_send_a_message(self):
        state=self.setup();self.assertTrue(state['connected']);self.assertTrue(state['enabled']);self.assertEqual(self.sent,[])
        self.assertNotIn(TOKEN,json.dumps(state));self.assertEqual(os.stat(self.service.secret).st_mode&0o777,0o600)
        self.assertNotIn(TOKEN,json.dumps(self.server.store.export_json()))
    def test_result_send_is_durable_idempotent_and_never_calls_models(self):
        self.setup()
        with patch('council.claude_call',side_effect=AssertionError('no model')),patch('council.codex_call',side_effect=AssertionError('no model')):
            first=self.service.enqueue(self.pid,'OFFLINE unique result');second=self.service.enqueue(self.pid,'OFFLINE unique result')
            self.assertEqual(first['id'],second['id']);self.service.process(self.row(first['id']))
        self.assertEqual(self.row(first['id'])['state'],'sent');self.assertEqual(len(self.sent),1)
    def test_uncertain_network_response_is_not_blindly_retried(self):
        self.setup();job=self.service.enqueue(self.pid,'OFFLINE timeout')
        with patch.object(SlackAPI,'request',side_effect=SlackError('OFFLINE lost response',uncertain=True)):self.service.process(self.row(job['id']))
        self.assertEqual(self.row(job['id'])['state'],'uncertain')
    def test_rate_limit_retries_and_disconnect_cancels_queued_messages(self):
        self.setup();job=self.service.enqueue(self.pid,'OFFLINE rate')
        with patch.object(SlackAPI,'request',side_effect=SlackError('OFFLINE rate',retry_after=30)):self.service.process(self.row(job['id']))
        self.assertEqual(self.row(job['id'])['state'],'queued');self.assertGreater(self.row(job['id'])['retry_at'],0)
        self.service.disconnect();self.assertFalse(self.service.secret.exists());self.assertEqual(self.row(job['id'])['state'],'cancelled')
    def test_notification_escapes_mentions_and_does_not_claim_missing_measurements(self):
        payload=message_for(dict(title='<!channel> '+TOKEN,goal='test',runs=[],brief={}))
        self.assertNotIn('<!channel>',payload['text']);self.assertNotIn(TOKEN,payload['text']);self.assertIn('정상 측정 0회',payload['text'])
    def test_parallel_study_notification_uses_only_its_own_results(self):
        from unittest.mock import Mock
        self.setup();folder=Path(self.server.store.db_path).parent/'council-runs'/'OFFLINE-study';folder.mkdir(parents=True)
        (folder/'native-completion.json').write_text(json.dumps(dict(job_id='study-a',run_ids=['run-a'])))
        data=dict(title='Project',goal='Goal',nodes=[dict(id='a',title='Hypothesis A')],runs=[dict(id='run-a',title='Own result',state='succeeded',metric='accuracy',analysis=dict(status='measured',value=.7)),dict(id='run-b',title='UNRELATED result',state='succeeded',metric='accuracy',analysis=dict(status='measured',value=.9))],brief=dict(findings='UNRELATED project summary'))
        with patch('slack_notifications.project_data',return_value=data),patch('slack_notifications.signature',return_value='OFFLINE digest'):
            job=self.service.enqueue(self.pid,'OFFLINE study-a',job=dict(id='study-a',node_id='a',run_dir=str(folder)))
        payload=json.loads(self.row(job['id'])['payload']);self.assertIn('Hypothesis A',payload['text']);self.assertIn('Own result',payload['text']);self.assertNotIn('UNRELATED',payload['text'])
    def test_notion_report_wait_does_not_send_private_queue_metadata(self):
        from unittest.mock import Mock
        self.setup();self.service.publications=Mock()
        self.service.publications.state.return_value=dict(connected=True,link=dict(auto_sync=True),jobs=[])
        with patch('slack_notifications.signature',return_value='OFFLINE digest'):job=self.service.enqueue(self.pid,'OFFLINE Notion wait')
        row=self.row(job['id']);self.service.process(row);self.assertEqual(self.sent,[])
        self.service.publications.state.return_value=dict(jobs=[dict(state='completed',digest='OFFLINE digest',page_url='https://www.notion.so/OFFLINE')])
        self.service.process(self.row(job['id']));self.assertEqual(len(self.sent),1)
        self.assertIn('https://www.notion.so/OFFLINE',self.sent[0]['text']);self.assertFalse(any(k.startswith('_') for k in self.sent[0]))
    def test_setup_status_and_connection_test_need_no_project(self):
        self.server.store.set_project_deleted(self.pid,True)
        with patch.object(self.client,'project',side_effect=AssertionError('global Slack must not select projects')),patch('sys.stdin',io.StringIO(TOKEN)):
            state=terminal.dispatch(self.client,terminal.parser().parse_args(['slack','setup','--member',MEMBER,'--token-stdin']))
            self.assertEqual(state['scope'],'all_projects');self.assertTrue(state['enabled'])
            result=terminal.dispatch(self.client,terminal.parser().parse_args(['slack','test','--request-id','OFFLINE-global-test']))
            self.service.process(self.row(result['id']))
        self.assertEqual(len(self.sent),1);self.assertEqual(self.row(result['id'])['project_id'],'')
        result=subprocess.run([sys.executable,str(fixtures.ROOT/'braindance.py'),'slack','status','--json','--db',str(self.server.store.db_path),'--server',self.client.url],capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(json.loads(result.stdout)['scope'],'all_projects')
    def test_one_connection_notifies_existing_and_future_projects_once(self):
        other=self.client.project(terminal.dispatch(self.client,terminal.parser().parse_args(['new','Existing other','--goal','OFFLINE']))['project_id'])
        self.completed_study('OFFLINE-historical',self.fixture.project,finished_at='2020-01-01T00:00:00+00:00');self.setup()
        future=self.client.project(terminal.dispatch(self.client,terminal.parser().parse_args(['new','Future project','--goal','OFFLINE']))['project_id'])
        self.completed_study('OFFLINE-existing',other);self.completed_study('OFFLINE-future',future)
        self.completed_study('OFFLINE-discovery',other,role='discovery')
        self.completed_study('OFFLINE-trash',self.fixture.project);self.server.store.set_project_deleted(self.pid,True)
        with patch('council.claude_call',side_effect=AssertionError('no model')),patch('council.codex_call',side_effect=AssertionError('no model')):
            self.service.tick();self.service.tick()
            with self.service.connect() as c:rows=[dict(r) for r in c.execute('SELECT * FROM deliveries')]
            self.assertEqual({r['event_key'] for r in rows},{'study:OFFLINE-existing','study:OFFLINE-future'})
            for row in rows:self.service.process(row)
        self.assertEqual(len(self.sent),2);self.assertTrue(any('Existing other' in p['text'] for p in self.sent));self.assertTrue(any('Future project' in p['text'] for p in self.sent))
    def test_upgrade_preserves_credentials_queue_and_enables_all_projects_without_backfill(self):
        self.setup();queued=self.service.enqueue(self.pid,'OFFLINE-preserved');secret=self.service.secret.read_bytes()
        with self.service.connect() as c:
            c.execute('DROP TABLE notification_settings');c.execute('INSERT INTO subscriptions VALUES(?,?,?)',(self.pid,1,'2020-01-01T00:00:00+00:00'))
        before=now();upgraded=SlackNotifications(self.server.store,autostart=False);self.addCleanup(upgraded.close)
        state=upgraded.state();self.assertTrue(state['enabled']);self.assertEqual(state['scope'],'all_projects');self.assertGreaterEqual(state['since'],before)
        self.assertEqual(secret,upgraded.secret.read_bytes());self.assertEqual(state['deliveries'][0]['id'],queued['id'])
    def test_resaving_keeps_cursor_but_reconnect_starts_with_new_results(self):
        state=self.setup();again=self.client.request('/api/slack/configure',dict(member_id=MEMBER))
        self.assertEqual(state['since'],again['since']);self.service.disconnect()
        self.completed_study('OFFLINE-while-disconnected',self.fixture.project)
        reconnected=self.client.request('/api/slack/configure',dict(member_id=MEMBER,token=TOKEN))
        self.assertGreater(reconnected['since'],state['since']);self.service.tick()
        self.assertEqual(reconnected['deliveries'],[]);self.assertEqual(self.sent,[])
    def test_deleted_project_does_not_block_other_projects_while_waiting_for_notion(self):
        from unittest.mock import Mock
        self.setup();self.service.publications=Mock();self.service.publications.state.return_value=dict(connected=True,link=dict(auto_sync=True),jobs=[])
        pending=self.service.enqueue(self.pid,'OFFLINE deleted pending Notion');self.server.store.set_project_deleted(self.pid,True)
        self.service.publications.state.side_effect=AssertionError('Deleted project must not block global notifications')
        self.service.process(self.row(pending['id']));self.assertEqual(self.row(pending['id'])['state'],'cancelled');self.assertEqual(self.sent,[])

    def test_rejected_study_is_reported_once_without_claiming_measurements(self):
        self.setup();self.completed_study('OFFLINE-rejected-study',self.fixture.project)
        with self.server.store._connect() as c:folder=Path(c.execute('SELECT run_dir FROM research_jobs WHERE id=?',('OFFLINE-rejected-study',)).fetchone()[0])
        path=folder/'native-completion.json';done=json.loads(path.read_text());done.update(outcome='rejected',reason='OFFLINE duplicate study rejected before execution');path.write_text(json.dumps(done))
        self.service.tick();self.service.tick()
        with self.service.connect() as c:rows=[dict(r) for r in c.execute('SELECT * FROM deliveries')]
        self.assertEqual(len(rows),1);self.service.process(rows[0]);self.assertEqual(len(self.sent),1)
        self.assertIn('가설 기각 보고',self.sent[0]['text']);self.assertIn('실험 미실행',self.sent[0]['text']);self.assertIn('OFFLINE duplicate',self.sent[0]['text']);self.assertNotIn('정상 측정',self.sent[0]['text'])
