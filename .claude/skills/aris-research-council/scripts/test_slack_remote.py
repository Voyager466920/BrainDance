"""Socket event fixtures exercise actual project/control/chat/outbox paths; no live Slack/LLM/GPU."""
import copy
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_slack_notifications as fixtures
from slack_remote import SlackRemote,target_key
from slack_notifications import SlackError,SlackAPI
from tree_store import now

APP_TOKEN='xapp-OFFLINE-fixture-not-a-real-app-secret'
BOT='U9999999999'


class RemoteTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.SlackNotificationTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.fixture.setup();self.server=self.fixture.server;self.remote=self.server.remote;self.store=self.server.store
        self.notifications=self.server.notifications;self.client=self.fixture.client;self.pid=self.fixture.pid
        validation=patch('slack_remote.validate_app');self.validate=validation.start();self.addCleanup(validation.stop)
        self.remote.configure(APP_TOKEN);self.serial=0
    def payload(self,text,thread=None,**event_changes):
        self.serial+=1;stamp=f'1793230000.{self.serial:06}'
        event=dict(type='message',channel_type='im',channel=fixtures.DM,user=fixtures.MEMBER,text=text,ts=stamp)
        if thread:event['thread_ts']=thread
        event.update(event_changes)
        return dict(type='event_callback',team_id='T0123456789',api_app_id='A0123456789',event_id='EvTEST'+str(self.serial),event=event,authorizations=[dict(team_id='T0123456789',user_id=BOT,is_bot=True)])
    def event(self,payload):
        with self.remote.db() as c:return dict(c.execute('SELECT * FROM remote_events WHERE event_id=?',(payload['event_id'],)).fetchone())
    def send(self,text,thread=None):
        payload=self.payload(text,thread);self.assertTrue(self.remote.receive(payload));self.remote.tick();return payload,self.event(payload)
    def select(self,project=None):return self.send('프로젝트 선택 '+(project or self.pid)[:8])
    def test_configuration_keeps_app_secret_local_and_never_posts_on_setup(self):
        self.assertEqual(self.fixture.sent,[]);self.assertEqual(os.stat(self.remote.secret).st_mode&0o777,0o600)
        self.assertNotIn(APP_TOKEN,json.dumps(self.remote.state()));self.assertNotIn(APP_TOKEN,json.dumps(self.store.export_json()))
        self.assertNotIn(APP_TOKEN,self.notifications.db.read_bytes().decode(errors='ignore'))
        self.validate.assert_called_once_with(APP_TOKEN,fixtures.TOKEN)
    def test_missing_dm_scope_is_reported_before_storing_an_app_token(self):
        self.remote.disable(forget=True)
        with patch('slack_remote.SlackAPI') as api:
            api.return_value.request.return_value=dict(ok=True,team_id='T0123456789',user_id=BOT)
            api.return_value.last_scopes={'chat:write','im:write'}
            with self.assertRaisesRegex(ValueError,'im:history'):self.remote.configure(APP_TOKEN)
        self.assertFalse(self.remote.secret.exists());self.assertFalse(self.remote.state()['enabled'])

    def test_owner_target_changes_invalidate_already_received_messages(self):
        self.select();payload=self.payload('중지');self.remote.receive(payload)
        creds=self.notifications.credentials();creds['member_id']='U0000000000';self.notifications.secret.write_text(json.dumps(creds))
        self.assertFalse(self.remote.active());self.remote.tick();self.assertEqual(self.event(payload)['state'],'pending')
        self.assertFalse(self.remote.receive(self.payload('상태')))

    def test_stop_is_available_when_the_project_model_reply_queue_is_full(self):
        self.select();root=self.client.root(self.fixture.fixture.project)
        for i in range(4):self.server.chat.send(dict(node_id=root['id'],content='대기 질문 '+str(i),mode='ask',request_id='full-reply-queue-000'+str(i)))
        _,row=self.send('중지');self.assertIn('중지를 요청',row['response'])
        with self.store._connect() as c:meta=json.loads(c.execute("SELECT metadata FROM research_chat WHERE request_id=? AND role='assistant'",(self.remote.request_id(row['id']),)).fetchone()[0])
        self.assertEqual(meta['reply_model_calls'],0)

    def test_uncertain_slack_send_is_not_automatically_posted_again(self):
        _,row=self.send('프로젝트 목록')
        with self.notifications.connect() as c:delivery=dict(c.execute('SELECT * FROM deliveries WHERE event_key=?',('remote:'+row['id']+':reply',)).fetchone())
        with patch.object(SlackAPI,'request',side_effect=SlackError('OFFLINE uncertain',uncertain=True)):self.notifications.process(delivery)
        self.remote.tick()
        with self.notifications.connect() as c:
            rows=c.execute('SELECT state FROM deliveries WHERE event_key=?',('remote:'+row['id']+':reply',)).fetchall()
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['state'],'uncertain')

    def test_owner_workspace_channel_bot_edits_and_authorizations_are_all_checked(self):
        base=self.payload('중지')
        mutations=[('user','U0000000000'),('channel','D0000000000'),('channel_type','channel'),('bot_id','B0000000000'),('subtype','message_changed'),('hidden',True)]
        for key,value in mutations:
            wrong=copy.deepcopy(base);wrong['event'][key]=value;self.assertFalse(self.remote.receive(wrong))
        wrong=copy.deepcopy(base);wrong['team_id']='TOTHER';self.assertFalse(self.remote.receive(wrong))
        wrong=copy.deepcopy(base);wrong['authorizations']=[];self.assertFalse(self.remote.receive(wrong))
        wrong=copy.deepcopy(base);wrong['authorizations']=[None];self.assertFalse(self.remote.receive(wrong))
        with self.remote.db() as c:self.assertEqual(c.execute('SELECT count(*) FROM remote_events').fetchone()[0],0)
    def test_socket_ack_follows_durable_persistence_and_invalid_messages_are_acked(self):
        payload=self.payload('프로젝트 목록');acks=[]
        client=SimpleNamespace(send_socket_mode_response=lambda value:acks.append(value.envelope_id))
        self.remote.on_socket(client,SimpleNamespace(type='events_api',payload=payload,envelope_id='envelope-one'))
        self.assertEqual(self.event(payload)['state'],'pending');self.assertEqual(acks,['envelope-one'])
        bad=copy.deepcopy(payload);bad['event']['user']='UOTHER'
        self.remote.on_socket(client,SimpleNamespace(type='events_api',payload=bad,envelope_id='envelope-two'))
        self.assertEqual(acks,['envelope-one','envelope-two'])
    def test_project_list_and_selection_are_explicit_and_do_not_call_a_model(self):
        with patch('council.codex_call',side_effect=AssertionError('No model')):
            _,row=self.send('프로젝트 목록');self.assertIn(self.pid[:8],row['response'])
            _,row=self.send('중지');self.assertIn('먼저 프로젝트',row['response'])
            _,row=self.select();self.assertEqual(row['project_id'],self.pid)
        self.assertEqual(self.remote.settings()['project_id'],self.pid)
    def test_new_experiment_is_saved_once_in_the_thread_project_without_a_model(self):
        selected,_=self.select();other=self.fixture.fixture.call('new','Other research','--goal','Other')
        self.select(other['project_id'])
        with patch('council.codex_call',side_effect=AssertionError('No model for request registration')):
            payload,row=self.send('새 실험: OFFLINE compare A and B',thread=selected['event']['ts'])
            self.assertEqual(row['state'],'completed');self.assertEqual(row['project_id'],self.pid)
            self.assertIn('새 실험을 추가',row['response']);self.remote.receive(payload);self.remote.tick()
        rows=self.store.export_json()['experiment_requests'];self.assertEqual(len(rows),1);self.assertEqual(rows[0]['project_id'],self.pid)
        with self.store._connect() as c:
            reply=c.execute("SELECT metadata,state FROM research_chat WHERE request_id=? AND role='assistant'",(self.remote.request_id(row['id']),)).fetchone()
        self.assertEqual(reply['state'],'completed');self.assertEqual(json.loads(reply['metadata'])['reply_model_calls'],0)

    def test_normal_message_and_reply_share_the_project_conversation_and_send_once(self):
        self.select();payload,row=self.send('기존 결과와 한계를 요약해줘')
        self.assertEqual(row['state'],'waiting_reply');reply=self.server.chat.get(row['chat_id'])
        self.assertEqual(reply['project_id'],self.pid);self.assertEqual(reply['metadata']['origin']['kind'],'slack_dm')
        self.assertEqual(reply['metadata']['mode'],'auto')
        self.server.chat.finish(reply['id'],'측정 결과만 요약한 답변','completed',reply['metadata'])
        self.remote.tick();self.remote.tick();self.assertTrue(self.remote.receive(payload));self.remote.tick()
        with self.store._connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM research_chat WHERE request_id=?',(self.remote.request_id(row['id']),)).fetchone()[0],2)
        with self.notifications.connect() as c:
            rows=c.execute('SELECT * FROM deliveries WHERE event_key=?',('remote:'+row['id']+':reply',)).fetchall();self.assertEqual(len(rows),1)
        self.notifications.process(dict(rows[0]));self.assertEqual(self.fixture.sent[-1]['thread_ts'],payload['event']['ts'])
        self.assertIn('측정 결과만 요약한 답변',self.fixture.sent[-1]['text'])
    def test_thread_binding_survives_project_switch_and_can_reply_to_result_notifications(self):
        self.select();first,row=self.send('첫 프로젝트 질문')
        other=self.fixture.fixture.call('new','Other research','--goal','Other')
        self.select(other['project_id']);_,follow=self.send('첫 질문에 추가',thread=first['event']['ts'])
        self.assertEqual(follow['project_id'],self.pid)
        self.remote.bind_thread('1793231000.000001',self.pid)
        _,follow=self.send('보고서에 추가 질문',thread='1793231000.000001');self.assertEqual(follow['project_id'],self.pid)
        _,unknown=self.send('모르는 대화 묶음',thread='1793231000.000002');self.assertIn('확인할 수 없습니다',unknown['response'])
        self.assertIsNone(unknown['project_id'])
    def test_can_select_in_an_unbound_project_list_thread_but_not_retarget_existing_research(self):
        listing,_=self.send('프로젝트 목록');_,selected=self.send('프로젝트 선택 '+self.pid[:8],thread=listing['event']['ts'])
        self.assertEqual(selected['project_id'],self.pid)
        other=self.fixture.fixture.call('new','Other research','--goal','Other')
        _,wrong=self.send('프로젝트 선택 '+other['project_id'][:8],thread=listing['event']['ts'])
        self.assertIn('바꾸지 않습니다',wrong['response']);self.assertEqual(self.remote.settings()['project_id'],self.pid)
    def test_stop_bypasses_model_queue_and_resume_reconfigures_the_same_session_once(self):
        self.select();item=self.server.autopilot.control(dict(project_id=self.pid,action='start',duration_seconds=3600,execution_policy='until_deadline'))['session']
        _,stopped=self.send('중지');self.assertIn('중지를 요청',stopped['response']);self.assertEqual(self.server.autopilot.get(item['id'])['status'],'stopped')
        payload,resumed=self.send('재개 2시간 보호 끄기')
        self.assertIn('2시간',resumed['response']);state=self.server.autopilot.get(item['id'])
        self.assertEqual(state['id'],item['id']);self.assertEqual(state['config']['duration_seconds'],7200);self.assertEqual(state['config']['continuation_count'],1)
        self.assertTrue(self.remote.receive(payload));self.remote.tick();self.assertEqual(self.server.autopilot.get(item['id'])['config']['continuation_count'],1)
        _,question=self.send('재개하면 어떻게 돼?');self.assertIn('형식으로',question['response']);self.assertEqual(self.server.autopilot.get(item['id'])['config']['continuation_count'],1)
    def test_guarded_resume_uses_existing_controller_and_fresh_allowance(self):
        from test_quota_guard import status
        self.select();item=self.server.autopilot.control(dict(project_id=self.pid,action='start',duration_seconds=3600,execution_policy='until_deadline'))['session']
        self.server.autopilot.control(dict(project_id=self.pid,action='stop'));self.server.autopilot.quota_status=lambda force=False:status(70,80)
        _,row=self.send('재개 30분 사용량 10%p');self.assertIn('10%p',row['response'])
        config=self.server.autopilot.get(item['id'])['config'];self.assertEqual(config['duration_seconds'],1800);self.assertEqual(config['quota_guard']['drop_percent'],10)
    def test_tokens_are_never_forwarded_to_model_or_saved_in_event_text(self):
        self.select();_,row=self.send('등록 '+APP_TOKEN)
        self.assertIn('숨김 입력',row['response']);self.assertNotIn(APP_TOKEN,json.dumps(row));self.assertIsNone(row['chat_id'])
    def test_disconnect_and_changed_targets_cancel_inbound_and_outbound_work(self):
        self.select();payload=self.payload('중지');self.remote.receive(payload)
        self.remote.disable();self.remote.tick();self.assertEqual(self.event(payload)['state'],'cancelled');self.assertFalse(self.remote.receive(self.payload('상태')))
        self.assertTrue(self.notifications.state()['connected']);self.assertTrue(self.remote.secret.exists())
        self.remote.configure(APP_TOKEN);payload,row=self.send('프로젝트 목록')
        with self.notifications.connect() as c:delivery=dict(c.execute('SELECT * FROM deliveries WHERE event_key=?',('remote:'+row['id']+':reply',)).fetchone())
        self.remote.disable();self.notifications.process(delivery)
        with self.notifications.connect() as c:self.assertEqual(c.execute('SELECT state FROM deliveries WHERE id=?',(delivery['id'],)).fetchone()[0],'cancelled')
    def test_restart_recovers_a_registered_chat_without_dispatching_a_second_model_request(self):
        self.select();payload,row=self.send('계속 같은 대화에서 정리해줘')
        with self.remote.db() as c:c.execute("UPDATE remote_events SET state='processing',chat_id=NULL WHERE id=?",(row['id'],))
        self.remote.close();restarted=SlackRemote(self.store,self.notifications,self.server.chat,self.server.autopilot,autostart=False);self.addCleanup(restarted.close)
        self.assertEqual(self.event(payload)['state'],'waiting_reply')
        with self.store._connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM research_chat WHERE request_id=?',(self.remote.request_id(row['id']),)).fetchone()[0],2)
    def test_restart_does_not_repeat_an_uncertain_control_operation(self):
        payload=self.payload('재개 2시간 보호 끄기');self.remote.receive(payload)
        with self.remote.db() as c:c.execute("UPDATE remote_events SET state='processing' WHERE event_id=?",(payload['event_id'],))
        self.remote.close();restarted=SlackRemote(self.store,self.notifications,self.server.chat,self.server.autopilot,autostart=False);self.addCleanup(restarted.close)
        self.assertEqual(self.event(payload)['state'],'uncertain');self.assertIn('반복하지 않았습니다',self.event(payload)['response'])
    def test_http_chat_payload_cannot_spoof_internal_slack_provenance_or_direct_replies(self):
        root=self.client.root(self.fixture.fixture.project)
        for extra in [dict(origin={'kind':'slack_dm'}),dict(direct_reply={'reply':'bypass'})]:
            with self.assertRaises(Exception):self.client.request('/api/chat/send',dict(node_id=root['id'],content='테스트',mode='ask',request_id='remote-spoof-denied-001',**extra))
