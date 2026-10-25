import json
from pathlib import Path
import tempfile
import unittest

import project_session
from council import dump
from tree_store import TreeStore
import test_research_chat as chat_fixture


class SessionTests(unittest.TestCase):
    def test_official_codex_thread_is_resumed_per_project_and_never_shared_across_projects(self):
        with tempfile.TemporaryDirectory() as work:
            store=TreeStore(Path(work)/'tree.sqlite3');one=store.add_node(None,'One',kind='problem');two=store.add_node(None,'Two',kind='problem')
            s1=project_session.identity(store,one['project_id']);s2=project_session.identity(store,two['project_id'])
            self.assertNotEqual(s1['id'],s2['id']);self.assertEqual(s1,project_session.identity(TreeStore(store.db_path),one['project_id']))
            seen=[]
            def invoke(folder,prompt,cfg,budget,engine):
                seen.append((cfg.get('_resume_thread'),cfg['_project_cwd']))
                dump(Path(folder)/'usage.json',dict(thread_id=cfg.get('_resume_thread') or 'thread-'+str(len(seen))))
                return dict(reply='fixture')
            for i,session in enumerate([s1,s1,s2,s1]):project_session.codex_call(Path(work)/str(i),'prompt',dict(project_session=session,timeout_seconds=5),None,'/offline',invoke)
            self.assertEqual([x[0] for x in seen],[None,'thread-1',None,'thread-1'])
            self.assertEqual(seen[0][1],seen[1][1]);self.assertNotEqual(seen[0][1],seen[2][1])


class SharedHistoryTests(unittest.TestCase):
    setUp=chat_fixture.ChatTests.setUp
    send=chat_fixture.ChatTests.send
    complete=chat_fixture.ChatTests.complete
    def test_experiment_preparation_and_conversation_receive_the_same_project_history(self):
        original='Direction: use the measured p95 from this conversation.'
        message=self.send(original);self.complete(message)
        from steering import prompt_context
        research=prompt_context(self.store,self.node['project_id'])['shared_project_session']
        chat=self.chat.context(self.send('What is the shared context?',mode='ask',request_id='message-shared-context-001'))['shared_project_session']
        self.assertEqual(research['session_id'],chat['session_id'])
        self.assertTrue(any(m['content']==original for m in research['conversation']))
        other=self.store.add_node(None,'Other project',kind='problem')
        context=project_session.context(self.store,other['project_id'])
        self.assertNotEqual(context['session_id'],research['session_id']);self.assertEqual(context['conversation'],[])
