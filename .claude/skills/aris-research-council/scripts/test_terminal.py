"""CLI integration checks against the real loopback API; no paid models or GPU."""
import argparse
import asyncio
import contextlib
import io
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import terminal
from viewer import create_server

ROOT=Path(__file__).resolve().parents[4]


class TerminalTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.db=Path(self.temp.name)/'tree.sqlite3'
        # Disable just the model dispatchers, retaining the real APIs/store/runner.
        self.patches=[patch('research_chat.ResearchChat._loop',return_value=None),patch('autopilot.Autopilot._loop',return_value=None)]
        for p in self.patches:p.start();self.addCleanup(p.stop)
        self.server=create_server(self.db,0)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.close_server)
        self.client=terminal.Client('http://127.0.0.1:'+str(self.server.server_address[1]),self.db)
        self.project=terminal.dispatch(self.client,terminal.parser().parse_args(['new','CLI fixture','--goal','Shared project fixture']))
        self.project=self.client.project(self.project['project_id'])

    def close_server(self):
        self.server.shutdown();self.thread.join(3);self.server.server_close()

    def call(self,*words):
        args=terminal.parser().parse_args(list(words));return terminal.dispatch(self.client,args,self.project)

    def test_shared_app_conversation_idempotency_and_project_isolation(self):
        request='cli-offline-request-0001'
        reply=self.call('chat','방향을 보존한 질문','--mode','ask','--no-wait','--request-id',request)
        repeated=self.call('chat','방향을 보존한 질문','--mode','ask','--no-wait','--request-id',request)
        self.assertEqual(reply['id'],repeated['id'])
        rows=self.server.chat.messages(self.project['id'])['messages']
        self.assertEqual(len(rows),2);self.assertEqual(rows[0]['content'],'방향을 보존한 질문')
        self.assertEqual(self.server.autopilot.state(self.project['id'])['directions'],[])
        self.server.chat.finish(reply['id'],'OFFLINE fixture reply','completed',reply['metadata'])
        self.assertEqual(self.call('history')[-1]['content'],'OFFLINE fixture reply')
        second=terminal.dispatch(self.client,terminal.parser().parse_args(['new','Other','--goal','Other project']))
        self.assertEqual(self.client.messages(self.client.project(second['project_id'])),[])

    def test_csrf_rotation_refreshes_without_replaying_a_successful_mutation(self):
        self.client.csrf='expired'
        self.call('chat','한 번만 전송','--mode','ask','--no-wait')
        self.assertEqual(len(self.server.chat.messages(self.project['id'])['messages']),2)
        self.assertEqual(self.client.csrf,self.server.csrf)

    def test_limits_and_issue_reply_use_same_project_session_and_preserve_charges(self):
        state=self.call('auto','start','--calls','10','--tokens','200000')
        session=state['session'];self.call('auto','pause')
        from session_budget import update
        ledger=session['config']['session_budget']
        update(ledger,'reserve',key='fixture-charge',calls=1,estimate=100)
        before=self.call('status')
        after=self.call('limits','--calls','15','--tokens','300000')
        self.assertEqual(after['session']['id'],session['id']);self.assertEqual(after['session']['status'],'paused')
        self.assertEqual(after['usage']['calls'],before['usage']['calls']);self.assertEqual(after['usage']['charged_tokens'],before['usage']['charged_tokens'])
        message=self.call('chat','장치는 유지해','--no-wait','--reply-to','session:'+session['id'])
        self.assertEqual(message['metadata']['reply_to']['id'],session['id'])

    def test_project_selection_rejects_duplicate_names_and_wrong_workspace(self):
        terminal.dispatch(self.client,terminal.parser().parse_args(['new','CLI fixture','--goal','Another']))
        with self.assertRaises(terminal.ClientError):self.client.project('CLI fixture')
        wrong=terminal.Client(self.client.url,self.db.with_name('other.sqlite3'))
        with self.assertRaisesRegex(terminal.ClientError,'작업공간'):wrong.health()

    def test_loopback_only_and_terminal_escape_filtering(self):
        for url in ['https://127.0.0.1:8766','http://example.com','http://user@localhost','http://localhost/foo','http://localhost/?x=y']:
            with self.assertRaises(terminal.ClientError):terminal.Client(url,self.db)
        self.assertEqual(terminal.safe_text('\x1b[31mhello\x1b[0m\x1b]52;c;secret\x07\u202e'),'hello')

    def test_source_command_json_does_not_emit_logo_or_color(self):
        result=subprocess.run([sys.executable,str(ROOT/'braindance.py'),'projects','--json','--server',self.client.url,'--db',str(self.db)],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout)[0]['id'],self.project['id']);self.assertNotIn('\x1b',result.stdout)

    def test_globals_before_and_after_command_and_human_limits(self):
        for words in [['--project','name','--json','status'],['status','--project','name','--json']]:
            args=terminal.parser().parse_args(words);self.assertEqual(args.project,'name');self.assertTrue(args.json)
        self.call('auto','start');state=self.call('limits','--calls','50')
        with contextlib.redirect_stdout(io.StringIO()) as out:terminal.output(state,argparse.Namespace(command='limits'))
        self.assertIn('/ 50',out.getvalue());self.assertNotIn('session_budget',out.getvalue())

    def test_cli_target_and_connection_use_existing_compute_validation(self):
        profile=self.call('connection','fixture-ssh')
        self.assertEqual(profile['host'],'fixture-ssh')
        with self.assertRaises(terminal.ClientError):self.call('target',profile['id'],'--devices','unverified-gpu')
        assignment=self.call('target','local','--devices','cpu','--minutes','2')
        self.assertEqual(assignment['time_budget_minutes'],2)

    def test_interactive_progress_prints_while_prompt_is_waiting(self):
        from prompt_toolkit import PromptSession
        from prompt_toolkit.input import create_pipe_input
        from prompt_toolkit.output import DummyOutput
        self.server.store.add_note(self.client.root(self.project)['id'],'analysis','Older report','HISTORICAL_VERBOSE_REPORT')
        console=terminal.Console(self.client,terminal.parser().parse_args(['--no-banner','--no-color']))
        async def scenario(pipe):
            async def events():
                await asyncio.sleep(.3)
                self.server.store.add_note(self.client.root(self.project)['id'],'analysis','Fixture report','BACKGROUND_SHARED_REPORT')
                await asyncio.sleep(2.1)
                pipe.send_text('/status\r/quit\r')
            task=asyncio.create_task(events())
            await asyncio.wait_for(console.run(),8);await task
        with create_pipe_input() as pipe, contextlib.redirect_stdout(io.StringIO()) as out:
            with patch('prompt_toolkit.PromptSession',side_effect=lambda **kw:PromptSession(input=pipe,output=DummyOutput(),**kw)):
                asyncio.run(scenario(pipe))
        self.assertIn('BACKGROUND_SHARED_REPORT',out.getvalue())
        self.assertNotIn('HISTORICAL_VERBOSE_REPORT',out.getvalue())
        self.assertEqual(console.project['id'],self.project['id'])


class TerminalLifecycleTests(unittest.TestCase):
    def test_frozen_backend_owns_assets_and_certificate_but_preserves_custom_ca(self):
        with patch.object(sys,'frozen',True,create=True),patch.object(sys,'_MEIPASS','/test/_MEI',create=True):
            with patch.dict(os.environ,{'SSL_CERT_FILE':'/test/_MEI/certifi/cacert.pem'}):
                environment=terminal.backend_environment()
                self.assertEqual(environment['PYINSTALLER_RESET_ENVIRONMENT'],'1');self.assertNotIn('SSL_CERT_FILE',environment)
            with patch.dict(os.environ,{'SSL_CERT_FILE':'/custom/ca.pem'}):
                self.assertEqual(terminal.backend_environment()['SSL_CERT_FILE'],'/custom/ca.pem')

    def test_ascii_banner_width_plain_output_and_launcher_safety(self):
        for width in [40,65,80,132,180]:
            text=terminal.banner(width)
            self.assertIn('BrainDance',text);self.assertLessEqual(max(map(len,text.splitlines())),width)
        result=subprocess.run([sys.executable,str(ROOT/'braindance.py')],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0);self.assertIn('BrainDance',result.stdout);self.assertNotIn('\x1b',result.stdout)
        self.assertIn('▉',result.stdout)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(terminal.install_launcher(folder));self.assertTrue(os.access(path,os.X_OK))
            result=subprocess.run([str(path)],capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0);self.assertIn('BrainDance',result.stdout)
            path.write_text('Unrelated existing command')
            with self.assertRaises(terminal.ClientError):terminal.install_launcher(folder)

    def test_cli_exit_keeps_one_background_server_and_second_client_attaches(self):
        with tempfile.TemporaryDirectory() as folder:
            with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
            db=Path(folder)/'tree.sqlite3';client=terminal.Client('http://127.0.0.1:'+str(port),db)
            command=[sys.executable,str(ROOT/'braindance.py'),'projects','--json','--db',str(db),'--port',str(port)]
            try:
                first=subprocess.run(command,capture_output=True,text=True,timeout=35)
                self.assertEqual(first.returncode,0,first.stderr);self.assertEqual(json.loads(first.stdout),[])
                health=client.health()
                second=subprocess.run(command,capture_output=True,text=True,timeout=10)
                self.assertEqual(second.returncode,0,second.stderr);self.assertEqual(client.health()['pid'],health['pid'])
                # Starting a second supervisor at another port must fail before touching running work.
                duplicate=subprocess.run([sys.executable,str(ROOT/'braindance.py'),'serve','--db',str(db),'--port','0'],capture_output=True,text=True,timeout=10)
                self.assertNotEqual(duplicate.returncode,0);self.assertIn('already owns',duplicate.stderr)
                self.assertEqual(client.health()['pid'],health['pid'])
            finally:
                try:os.kill(client.health()['pid'],signal.SIGTERM)
                except (OSError,terminal.ClientError):pass
                deadline=time.monotonic()+5
                while time.monotonic()<deadline:
                    try:client.health();time.sleep(.1)
                    except OSError:break


if __name__=='__main__':unittest.main()
