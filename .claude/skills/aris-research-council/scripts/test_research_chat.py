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
from research_chat import ResearchChat
from tree_store import TreeStore
import steering

FIXTURE='''
import json,sys
from pathlib import Path
from unittest.mock import patch
import research_worker
def reply(folder,prompt,*args):
 job=json.loads(Path(sys.argv[1]).read_text());ctx=job['chat_context'];message=ctx['user_message']
 intent='direction' if message.startswith('Direction') else 'pause' if message.startswith('Pause') else 'stop' if message.startswith('Stop') else 'question'
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
