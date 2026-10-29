"""Continuation checkpoints use synthetic quotas and offline jobs; no model/GPU calls."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_terminal as fixtures
from test_quota_guard import status
from project_session import identity
from session_budget import update
from tree_store import now


class ContinuationTests(unittest.TestCase):
    setUp=fixtures.TerminalTests.setUp
    close_server=fixtures.TerminalTests.close_server
    def start(self,quota=20):
        self.server.autopilot.quota_status=lambda force=False:status()
        return self.server.autopilot.control(dict(project_id=self.project['id'],action='start',execution_policy='until_deadline',duration_seconds=3600,orchestration='hypothesis-tasks',quota_drop_percent=quota))['session']
    def task(self,item,key,state,message=''):
        from research_tasks import initialize
        initialize(self.server.store)
        node=self.server.store.add_node(self.client.root(self.project)['id'],key,kind='hypothesis')
        folder=Path(self.temp.name)/key;folder.mkdir()
        with self.server.store._connect() as c:c.execute('INSERT INTO research_tasks VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(key,item['id'],item['project_id'],node['id'],0,state,None,str(folder),'[]',2,0,now(),now(),message))
        return node,folder
    def renew(self,item,**changes):
        return self.client.request('/api/control/automatic',dict(project_id=item['project_id'],session_id=item['id'],action='resume',duration_seconds=7200,**changes))['session']

    def test_quota_stopped_session_keeps_history_counters_workspaces_and_unfinished_tasks(self):
        item=self.start();ledger=Path(item['config']['session_budget']);shared=identity(self.server.store,item['project_id'])
        root=self.client.root(self.project)
        reply=self.server.chat.send(dict(node_id=root['id'],content='기존 방향 지시',mode='ask',request_id='before-continuation-0001'))
        self.server.chat.finish(reply['id'],'기존 연구 대화','completed',reply['metadata'])
        update(ledger,'reserve',key='existing-call',calls=3,estimate=120);update(ledger,'record',key='existing-call',tokens=80)
        _,work=self.task(item,'unfinished','queued');(work/'experiment.py').write_text('# Existing experiment source; preserve')
        self.task(item,'finished','completed');self.task(item,'rejected','rejected')
        self.task(item,'manual-stop','stopped','사용자가 이 가설 작업을 중지했습니다.')
        self.server.autopilot.quota_status=lambda force=False:status(30,70);self.server.autopilot.tick(item)
        self.assertEqual(self.server.autopilot.get(item['id'])['status'],'stopped')
        before=json.loads(ledger.read_text());self.assertIn('quota_stop',before)
        self.server.autopilot.quota_status=lambda force=False:status(60,70)
        after=self.renew(item,quota_drop_percent=10)
        self.assertEqual(after['id'],item['id']);self.assertEqual(after['config']['native_workspace'],item['config']['native_workspace'])
        self.assertEqual(identity(self.server.store,item['project_id']),shared)
        self.assertEqual(after['config']['duration_seconds'],7200);self.assertEqual(after['progress']['phase'],'tasks')
        baseline=after['config']['quota_guard']['baseline']['providers'][0]['windows'][0]['remaining_percent'];self.assertEqual(baseline,60)
        raw=json.loads(ledger.read_text());self.assertEqual(raw['calls'],before['calls']);self.assertEqual(raw['charges'],before['charges']);self.assertEqual(raw['observed'],before['observed'])
        self.assertNotIn('quota_stop',raw);self.assertEqual(raw['continuations'][0]['before']['quota_stop'],before['quota_stop'])
        from research_tasks import listing
        tasks={r['id']:r for r in listing(self.server.store,item['id'])}
        self.assertEqual(tasks['unfinished']['state'],'queued');self.assertEqual(tasks['unfinished']['workspace'],str(work))
        self.assertEqual(tasks['finished']['state'],'completed');self.assertEqual(tasks['rejected']['state'],'rejected');self.assertEqual(tasks['manual-stop']['state'],'stopped')
        self.assertEqual((work/'experiment.py').read_text(),'# Existing experiment source; preserve')
        self.assertEqual(len([m for m in self.server.chat.messages(item['project_id'])['messages'] if m.get('role') in {'user','assistant'}]),2)
        update(ledger,'reserve',key='new-call',calls=1,estimate=1);self.assertEqual(json.loads(ledger.read_text())['calls'],4)
        self.server.autopilot.quota_status=lambda force=False:status(50,70)
        self.assertFalse(self.server.autopilot.check_quota(self.server.autopilot.get(item['id']),force=True))

    def test_completion_received_before_stop_is_not_requeued(self):
        item=self.start(quota=None);node,work=self.task(item,'late-completed','queued')
        identity='OFFLINE-late-completion';folder=Path(self.temp.name)/'council-runs'/identity;folder.mkdir(parents=True)
        (folder/'native-completion.json').write_text(json.dumps(dict(job_id=identity,outcome='measured',run_ids=[])))
        with self.server.store._connect() as c:
            c.execute('INSERT INTO research_jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(identity,item['project_id'],node['id'],'OFFLINE completion','completed','native-completed','Done','lite','{}',str(folder),now(),now(),now(),None))
            c.execute("UPDATE research_tasks SET state='running',job_id=? WHERE id='late-completed'",(identity,))
        self.server.autopilot.control(dict(project_id=item['project_id'],action='stop'))
        self.renew(item,quota_drop_percent=None)
        with self.server.store._connect() as c:row=c.execute("SELECT state,job_id FROM research_tasks WHERE id='late-completed'").fetchone()
        self.assertEqual(row['state'],'completed');self.assertEqual(row['job_id'],identity)

    def test_invalid_resume_leaves_stopped_session_and_ledger_untouched(self):
        item=self.start();self.server.autopilot.control(dict(project_id=item['project_id'],action='stop'))
        path=Path(item['config']['session_budget']);before=path.read_bytes()
        for changes in [dict(session_id='wrong'),dict(duration_seconds=0)]:
            payload=dict(project_id=item['project_id'],session_id=item['id'],action='resume',duration_seconds=3600);payload.update(changes)
            with self.assertRaises(Exception):self.client.request('/api/control/automatic',payload)
            self.assertEqual(path.read_bytes(),before)
        self.server.autopilot.quota_status=lambda force=False:dict(providers=[])
        with self.assertRaises(Exception):self.renew(item,quota_drop_percent=10)
        self.assertEqual(path.read_bytes(),before);self.assertEqual(self.server.autopilot.get(item['id'])['status'],'stopped')

    def test_cli_can_explicitly_disable_guard_without_a_usage_query(self):
        import terminal
        item=self.start();self.server.autopilot.control(dict(project_id=item['project_id'],action='stop'))
        self.server.autopilot.quota_status=lambda **kw:(_ for _ in ()).throw(AssertionError('Guard disabled; no quota request'))
        result=terminal.dispatch(self.client,terminal.parser().parse_args(['auto','resume','--hours','2','--no-quota-guard']),self.project)
        self.assertEqual(result['session']['id'],item['id']);self.assertNotIn('quota_guard',result['session']['config'])
        self.assertEqual(result['session']['config']['duration_seconds'],7200)

    def test_expired_session_can_continue_but_plain_pause_resume_keeps_its_deadline(self):
        item=self.start(quota=None);self.server.autopilot.control(dict(project_id=item['project_id'],action='pause'))
        ledger=Path(item['config']['session_budget']);before=ledger.read_bytes()
        resumed=self.server.autopilot.control(dict(project_id=item['project_id'],action='resume'))['session']
        self.assertEqual(resumed['config']['deadline_epoch'],item['config']['deadline_epoch']);self.assertEqual(ledger.read_bytes(),before)
        self.server.autopilot.expire(resumed);self.assertEqual(self.server.autopilot.get(item['id'])['status'],'completed')
        updated=self.renew(item,quota_drop_percent=None);self.assertEqual(updated['id'],item['id']);self.assertEqual(updated['status'],'running')

    def test_rate_limited_usage_does_not_claim_claude_is_disconnected(self):
        from quota_guard import capture
        from terminal_presenter import provider_line
        limited=status();limited['providers'][1].update(connection='authenticated',usage_state='rate_limited',windows=[])
        text=provider_line(limited);self.assertIn('Claude 연결됨',text);self.assertIn('조회 일시 제한(429)',text);self.assertNotIn('로그인 필요',text)
        with self.assertRaisesRegex(ValueError,'로그인은 연결'):capture(limited,20)
