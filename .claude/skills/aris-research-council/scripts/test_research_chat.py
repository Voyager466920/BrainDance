"""Research chat uses disposable workspaces, fixture model replies and real CPU jobs."""
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from autopilot import Autopilot
from compute import ComputeSettings
from experiments import ExperimentEngine
from project_cleanup import ProjectCleanup
from research import ResearchEngine
from research_chat import ResearchChat,explicit_literature_request,explicit_action_request
from tree_store import TreeStore
import steering

FIXTURE='''
import json,sys
from pathlib import Path
from unittest.mock import patch
import research_worker
def reply(folder,prompt,*args):
 job=json.loads(Path(sys.argv[1]).read_text());ctx=job['chat_context'];message=ctx['user_message']
 intent=message.split(':',1)[1].split('|',1)[0] if message.startswith('Misclassified:') else 'execute' if message.startswith('Run experiment') else 'literature' if message.startswith('Find papers') else 'publish' if message.startswith('Publish') else 'report' if message.startswith('Report') else 'direction' if message.startswith('Direction') else 'pause' if message.startswith('Pause') else 'stop' if message.startswith('Stop') else 'question'
 return dict(reply='OFFLINE fixture reply based on actual captured project state.',intent=intent)
with patch('lab_worker.council.codex_call',side_effect=reply):sys.exit(research_worker.run(sys.argv[1]))
'''


class ChatTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.store=TreeStore(self.root/'tree.sqlite3');self.node=self.store.add_node(None,'Chat infrastructure test',kind='problem')
        self.compute=ComputeSettings(self.root/'compute.json');self.compute.assign(self.node['project_id'],dict(profile_id='local',device_ids=['cpu'],time_budget_minutes=1))
        self.experiments=ExperimentEngine(self.store,self.compute,self.compute.state);self.addCleanup(self.experiments.close)
        self.research=ResearchEngine(self.store,self.experiments);self.addCleanup(self.research.close)
        self.control=Autopilot(self.store,self.research,self.experiments,autostart=False);self.addCleanup(self.control.close)
        self.chat=ResearchChat(self.store,self.research,self.control,autostart=False);self.addCleanup(self.chat.close)
        self.script=self.root/'fixture.py';self.script.write_text('import sys\nsys.path.insert(0,'+repr(str(Path(__file__).parent))+')\n'+FIXTURE)
        self.research.command=lambda:[sys.executable,'-u',str(self.script)]
        self.research.availability=lambda:dict(available=True,missing=[],aris_repo='/offline-fixture')

    def send(self,content='What is actually running?',mode='auto',request_id='message-fixture-0001'):
        return self.chat.send(dict(node_id=self.node['id'],content=content,mode=mode,request_id=request_id))

    def complete(self,message):
        self.chat.execute(message);actual=self.chat.get(message['id']);self.assertEqual(actual['state'],'completed',actual['content']);return actual

    def expire_research(self):
        session=self.control.control(dict(project_id=self.node['project_id'],action='start',execution_policy='until_deadline',duration_seconds=60))['session']
        ledger=Path(session['config']['session_budget']);data=json.loads(ledger.read_text());data['deadline_epoch']=time.time()-5;ledger.write_text(json.dumps(data))
        session['config']['deadline_epoch']=data['deadline_epoch']
        with self.store._connect() as conn:conn.execute('UPDATE automatic_sessions SET config=? WHERE id=?',(json.dumps(session['config']),session['id']))
        self.control.save(session,'completed','Research deadline reached in offline fixture.')
        return session,ledger

    def test_expired_research_still_answers_in_same_project_without_charging_or_resuming_it(self):
        from project_session import identity
        session,ledger=self.expire_research();before=ledger.read_bytes();shared=identity(self.store,self.node['project_id'])
        for i,mode in enumerate(['auto','ask']):
            reply=self.complete(self.send('지금까지의 실험 결과를 정리해줘',mode=mode,request_id='expired-conversation-'+str(i)))
            job=json.loads((self.research.root/('chat-'+reply['id'])/'job.json').read_text())
            self.assertNotIn('session_budget',job);self.assertEqual(job['project_session']['id'],shared['id'])
            self.assertEqual(job['chat_context']['actual_session']['id'],session['id'])
            self.assertEqual(reply['metadata']['reply_budget_scope'],'conversation_reply')
        self.assertEqual(ledger.read_bytes(),before);self.assertEqual(self.control.get(session['id'])['status'],'completed')
        self.assertEqual(self.research.list(self.node['project_id'])['jobs'],[]);self.assertEqual(self.control.state(self.node['project_id'])['runs'],[])

    def test_legacy_chat_job_cannot_reintroduce_an_expired_research_ledger(self):
        import lab_worker
        from unittest.mock import Mock
        _,ledger=self.expire_research();before=ledger.read_bytes();folder=self.root/'legacy-chat';folder.mkdir()
        job=dict(phase_timeout_seconds=60,session_budget=str(ledger),aris_repo='/offline-fixture',chat_context=dict(mode='ask',user_message='Summarize retained results',allowed_actions=[]))
        def actual_admission(path,prompt,cfg,budget,*args):
            self.assertNotIn('session_budget',cfg);budget.reserve(1,100)
            return dict(reply='OFFLINE reply after actual reply-budget admission',intent='question')
        with patch('lab_worker.council.codex_call',side_effect=actual_admission):lab_worker.chat(job,folder,Mock())
        self.assertEqual(json.loads((folder/'chat-response.json').read_text())['intent'],'question')
        self.assertEqual(ledger.read_bytes(),before);self.assertEqual(json.loads((folder/'chat-usage.json').read_text())['model_invocations_reserved'],1)

    def test_exhausted_bounded_research_budget_does_not_block_a_question(self):
        session=self.control.control(dict(project_id=self.node['project_id'],action='start'))['session']
        ledger=Path(session['config']['session_budget']);data=json.loads(ledger.read_text());data['calls']=data['max_calls'];ledger.write_text(json.dumps(data));before=ledger.read_bytes()
        self.control.save(session,'blocked','Offline research-call limit reached.')
        self.complete(self.send('What do these results mean?',mode='ask'))
        self.assertEqual(ledger.read_bytes(),before);self.assertEqual(self.control.get(session['id'])['status'],'blocked')

    def test_misclassified_questions_cannot_start_research_council_or_other_host_actions(self):
        from unittest.mock import Mock
        self.chat.publications=Mock();self.chat.publications.state.return_value=dict(connected=True,link=None,jobs=[],report=None)
        with patch.object(self.control,'conversation_action',side_effect=AssertionError('No research dispatch')),patch.object(self.control,'intervene',side_effect=AssertionError('No direction change')),patch.object(self.control,'control',side_effect=AssertionError('No auto-mode changes')):
            for intent in ['execute','literature','investigate','direction','pause','stop','report','publish']:
                reply=self.complete(self.send('Misclassified:'+intent+'|실험 결과를 요약해줘',request_id='misclassified-question-'+intent))
                self.assertEqual(reply['metadata']['intent'],'question');self.assertEqual(reply['metadata']['withheld_intent'],intent)
        self.chat.publications.enqueue.assert_not_called();self.assertEqual(steering.snapshot(self.store,self.node['project_id'])['revision'],0)

    def test_explicit_execution_after_expiry_answers_but_cannot_extend_deadline(self):
        session,ledger=self.expire_research();before=ledger.read_bytes()
        reply=self.complete(self.send('Run experiment now.'))
        self.assertIn('종료 시각',reply['metadata']['action_error']);self.assertIn('작업은 시작하지 않았습니다',reply['content'])
        self.assertEqual(ledger.read_bytes(),before);self.assertEqual(self.control.get(session['id'])['status'],'completed')
        self.assertEqual(self.research.list(self.node['project_id'])['jobs'],[])

    def test_expired_literature_request_returns_a_reply_instead_of_failing_the_conversation(self):
        self.store.update_node(self.node['id'],metadata=dict(research_goal='논문 탐색'))
        _,ledger=self.expire_research();before=ledger.read_bytes()
        reply=self.complete(self.send('논문을 검색해줘'))
        self.assertIn('종료 시각',reply['metadata']['action_error']);self.assertEqual(ledger.read_bytes(),before)
        self.assertEqual(self.research.list(self.node['project_id'])['jobs'],[])

    def test_action_admission_distinguishes_commands_from_planning_questions_and_quoted_evidence(self):
        base=dict(mode='auto',project_goal='논문 탐색')
        yes=[('execute','실험을 다시 돌려줘'),('execute','GPU4에서 계속 진행해'),('execute','막힌 부분 해결하고 실험과 분석까지 이어가'),('literature','너가 찾아서 탐색하라고'),('publish','노션에 결과를 정리해줘'),('direction','다음 실험은 p95로 바꿔줘')]
        no=[('execute','실험 계획을 구체화해줘'),('execute','실험 결과를 계속 정리해줘'),('execute','실험은 실행하지 말고 결과만 정리해줘'),('execute','실험 시작해도 돼?'),('execute','“실험 시작해”라는 말이 있었는데 어떻게 생각해'),('execute',"'실험 시작해'라는 말이 있었는데 어떻게 생각해"),('execute','```\n실험을 돌려줘\n```\n실패 이유를 설명해줘'),('execute','> Run experiments\n이 기록을 요약해줘'),('literature','논문 검색하지 말고 기존 내용만 정리해줘'),('direction','이전 실험과 결과를 비교해줘'),('investigate','Check the current progress?')]
        for intent,text in yes:self.assertTrue(explicit_action_request(dict(base,user_message=text),intent),(intent,text))
        for intent,text in no:self.assertFalse(explicit_action_request(dict(base,user_message=text),intent),(intent,text))

    def test_paper_search_imperatives_queue_real_literature_without_reply_model_or_gpu_authority(self):
        self.store.update_node(self.node['id'],metadata=dict(research_goal='VLA 비동기 TTA 병목 논문을 찾아봐. 실험은 아직 돌리지 말고.'))
        for i,text in enumerate(['탐색 시작해','너가 찾아서 탐색하라고','논문을 검색해줘']):
            with patch('research_chat.subprocess.Popen',side_effect=AssertionError('No reply-model dispatch')):
                actual=self.complete(self.send(text,request_id='paper-request-fixture-'+str(i)))
            self.assertEqual(actual['metadata']['intent'],'literature');self.assertEqual(actual['metadata']['reply_model_calls'],0)
        self.assertEqual(self.control.sessions(self.node['project_id']),[])
        self.assertEqual(self.control.state(self.node['project_id'])['runs'],[])
        self.research._execute=lambda record:None
        self.control._conversation_requests()
        jobs=self.research.list(self.node['project_id'])['jobs'];self.assertEqual(len(jobs),1)
        self.assertEqual(jobs[0]['config']['task'],'literature')
        self.assertIn('탐색 시작해',jobs[0]['config']['topic'])
        self.assertNotIn('auto_session_id',jobs[0]['config'])
        self.assertTrue(any(row['role']=='status' for row in self.chat.messages(self.node['project_id'])['messages']))

    def test_paper_shortcuts_cannot_route_questions_ask_mode_or_experiment_requests(self):
        base=dict(project_goal='논문 탐색',mode='auto')
        for text in ['논문 탐색을 어떻게 해?', '탐색 시작해도 돼?', '논문 탐색해보고 실험까지 돌려','탐색이 시작했어','논문 탐색해볼까']:
            self.assertFalse(explicit_literature_request(dict(base,user_message=text)),text)
        self.assertFalse(explicit_literature_request(dict(base,user_message='탐색 시작해',mode='ask')))

    def test_report_and_notion_intents_use_the_same_project_without_starting_experiments(self):
        from unittest.mock import Mock
        self.chat.publications=Mock();self.chat.publications.state.return_value=dict(connected=True,link=None,jobs=[],report=None);self.chat.publications.enqueue.return_value=dict(id='publication-fixture',state='queued')
        reply=self.complete(self.send('Publish results in Notion'))
        self.chat.publications.enqueue.assert_called_once_with(self.node['project_id'],publish=True)
        self.assertEqual(reply['metadata']['publication_job'],'publication-fixture')
        self.chat.publications.reset_mock()
        self.complete(self.send('Report retained measurements',request_id='report-fixture-0002'))
        self.chat.publications.enqueue.assert_called_once_with(self.node['project_id'],publish=False)
        self.chat.publications.reset_mock()
        self.complete(self.send('Publish question-only fixture',mode='ask',request_id='report-fixture-0003'))
        self.chat.publications.enqueue.assert_not_called()
        self.assertEqual(self.control.state(self.node['project_id'])['runs'],[])

    def test_reply_runs_independently_while_research_slot_and_cpu_experiment_are_busy(self):
        plan=self.experiments.create(dict(node_id=self.node['id'],title='Live CPU fixture',timeout_seconds=8,code="import time\nprint('ACTUAL_CPU_PROGRESS',flush=True)\ntime.sleep(5)"))
        approval=self.experiments.approve(plan['id'],plan['digest'],True);run=self.experiments.enqueue(plan['id'],approval['id'])
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            if 'ACTUAL_CPU_PROGRESS' in self.experiments.run_info(run['id'])['stdout_tail']:break
            time.sleep(.03)
        self.research.active_id='occupied-research-slot'
        message=self.send(mode='ask');self.complete(message)
        self.assertEqual(self.experiments.run_info(run['id'])['state'],'running')
        context=json.loads((self.research.root/('chat-'+message['id'])/'job.json').read_text())['chat_context']
        self.assertIn('ACTUAL_CPU_PROGRESS',context['current_runs'][0]['stdout_tail']);self.assertEqual(context['current_runs'][0]['title'],'Live CPU fixture')
        self.assertEqual(steering.snapshot(self.store,self.node['project_id'])['revision'],0)
        self.research.active_id=None

    def test_explicit_direction_applies_before_reply_and_duplicate_send_is_idempotent(self):
        message=self.send('Direction: compare p95 instead of mean.',mode='next')
        revision=steering.snapshot(self.store,self.node['project_id'])['revision'];self.assertGreater(revision,0)
        self.assertEqual(self.send('Direction: compare p95 instead of mean.',mode='next')['id'],message['id'])
        self.complete(message)
        self.assertEqual(len(steering.snapshot(self.store,self.node['project_id'])['directions']),1)
        with self.assertRaises(ValueError):self.send('Changed message under reused ID',mode='next')

    def test_question_only_cannot_apply_even_a_model_direction_intent(self):
        self.complete(self.send('Direction-looking text is a question only.',mode='ask'))
        self.assertEqual(steering.snapshot(self.store,self.node['project_id'])['revision'],0)

    def test_rejected_direction_is_an_explicit_failure_without_a_model_dispatch(self):
        self.store.update_node(self.node['id'],status='held')
        message=self.send('Direction: cannot change a held node.',mode='next')
        self.assertEqual(message['state'],'failed');self.assertIn('적용하지 못했습니다',message['content'])
        self.assertEqual(steering.snapshot(self.store,self.node['project_id'])['revision'],0)
        self.assertFalse((self.research.root/('chat-'+message['id'])).exists())

    def test_natural_direction_uses_original_human_text_and_not_model_rewrite(self):
        text='Direction: preserve the existing checkpoint.';actual=self.complete(self.send(text))
        self.assertGreater(actual['metadata']['direction_applied'],0)
        self.assertEqual(steering.snapshot(self.store,self.node['project_id'])['directions'][-1]['content'],text)

    def test_late_model_direction_does_not_overwrite_a_newer_human_instruction(self):
        message=self.send('Direction: older proposed comparison.');original=self.chat.context
        def context(item):
            value=original(item);self.control.intervene(dict(node_id=self.node['id'],content='Newer explicit instruction',apply_mode='next'));return value
        with patch.object(self.chat,'context',side_effect=context):self.complete(message)
        directions=steering.snapshot(self.store,self.node['project_id'])['directions'];self.assertEqual(len(directions),1);self.assertEqual(directions[0]['content'],'Newer explicit instruction')

    def test_pause_in_conversation_controls_only_this_project(self):
        session=self.control.control(dict(project_id=self.node['project_id'],action='start'))['session']
        actual=self.complete(self.send('Pause this project now.'))
        self.assertEqual(self.control.get(session['id'])['status'],'paused');self.assertEqual(actual['metadata']['control_applied'],'pause')

    def test_reports_and_messages_persist_and_interrupted_replies_do_not_replay(self):
        message=self.send();self.store.add_note(self.node['id'],'result','Actual result receipt','exit code 1, metrics unavailable')
        self.chat.close();reopened=ResearchChat(self.store,self.research,self.control,autostart=False);self.addCleanup(reopened.close)
        self.assertEqual(reopened.get(message['id'])['state'],'interrupted')
        rows=reopened.messages(self.node['project_id'])['messages'];self.assertTrue(any(m['role']=='report' and 'exit code 1' in m['content'] for m in rows))
        self.assertFalse((self.research.root/('chat-'+message['id'])).exists())

    def test_issue_reply_preserves_source_context_in_the_single_project_stream(self):
        session=self.control.control(dict(project_id=self.node['project_id'],action='start'))['session']
        self.control.save(session,'blocked','Need a confirmed evaluation entry point.')
        payload=dict(node_id=self.node['id'],content='Direction: use the existing evaluator.',mode='next',request_id='message-issue-reply-001',reply_to=dict(type='session',id=session['id']))
        message=self.chat.send(payload)
        self.assertEqual(self.chat.send(payload)['id'],message['id'])
        self.assertEqual(message['metadata']['reply_to']['message'],'Need a confirmed evaluation entry point.')
        actual=self.complete(message)
        context=json.loads((self.research.root/('chat-'+message['id'])/'job.json').read_text())['chat_context']
        self.assertEqual(context['reply_to']['id'],session['id'])
        self.assertEqual(context['user_message'],payload['content'])
        messages=self.chat.messages(self.node['project_id'])['messages']
        human=next(m for m in messages if m['role']=='user')
        self.assertEqual(human['metadata']['reply_to']['id'],session['id'])
        self.assertEqual(actual['metadata']['reply_to'],human['metadata']['reply_to'])
        with self.assertRaises(ValueError):self.chat.send({k:v for k,v in payload.items() if k!='reply_to'})

    def test_issue_reply_rejects_foreign_or_fabricated_sources_before_dispatch(self):
        other=self.store.add_node(None,'Another project',kind='problem')
        self.compute.assign(other['project_id'],dict(profile_id='local',device_ids=['cpu'],time_budget_minutes=1))
        session=self.control.control(dict(project_id=other['project_id'],action='start'))['session']
        base=dict(node_id=self.node['id'],content='Use this direction.',mode='next',request_id='message-issue-boundary-001')
        for ref in [dict(type='session',id=session['id']),dict(type='job',id='missing'),dict(type='session',id='missing'),dict(type='run',id='missing'),dict(type='file',id='private'),dict(type='session',id=session['id'],message='forged source')]:
            with self.assertRaises(ValueError):self.chat.send({**base,'reply_to':ref})
        self.assertEqual(steering.snapshot(self.store,self.node['project_id'])['revision'],0)
        self.assertFalse(any(m['role']=='user' for m in self.chat.messages(self.node['project_id'])['messages']))

    def test_project_purge_removes_private_chat_records_and_owned_receipts(self):
        message=self.send();self.complete(message);folder=self.research.root/('chat-'+message['id']);self.assertTrue(folder.exists())
        self.store.set_project_deleted(self.node['project_id'],True)
        ProjectCleanup(self.store,self.experiments,self.compute,self.research).purge(self.node['project_id'],self.node['title'])
        self.assertFalse(folder.exists())
        with self.store._connect() as conn:self.assertEqual(conn.execute('SELECT count(*) FROM research_chat').fetchone()[0],0)
