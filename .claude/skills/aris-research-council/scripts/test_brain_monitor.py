"""Independent monitor tests: disposable records, fake Slack, no models or SSH."""
import contextlib
import io
import json
from pathlib import Path
import plistlib
import sqlite3
import time
import unittest
from unittest.mock import patch

import brain_monitor as monitor
import terminal
import test_terminal as fixtures
from tree_store import now

TOKEN='xoxb-OFFLINE-monitor-fixture-not-a-real-token'


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.TerminalTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.server=self.fixture.server;self.db=self.fixture.db;self.pid=self.fixture.project['id'];self.clock=time.time()
        self.session=self.server.autopilot.control(dict(project_id=self.pid,action='start',execution_policy='until_deadline',duration_seconds=3600))['session']
        self.job='monitor-offline-job';self.folder=self.db.parent/'council-runs'/self.job;self.folder.mkdir(parents=True)
        self.log=self.folder/'native.stdout.jsonl';self.log.write_text('')
        with self.server.store._connect() as c:c.execute('INSERT INTO research_jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(self.job,self.pid,self.pid,'OFFLINE','running','verification','OFFLINE pending','lite','{}',str(self.folder),now(),now(),None,None))
        self.sent=[];root=self.db.parent/'integrations'
        (root/'slack-credentials.json').write_text(json.dumps(dict(token=TOKEN,channel='D0123456789',member_id='U0123456789',team_id='T0123456789')))
        with self.server.notifications.connect() as c:c.execute('UPDATE notification_settings SET enabled=1')
    def check(self,seconds=0,**options):
        options.setdefault('sender',lambda target,text,ca:(self.sent.append(text) or ('sent',0)))
        return monitor.check(self.db,self.fixture.client.url,clock=self.clock+seconds,probe=options.pop('probe',lambda *args:True),**options)
    def append(self,identity,error=False,text='OK',kind='tool_result'):
        with self.log.open('a') as f:f.write(json.dumps(dict(type='user',message=dict(content=[dict(type=kind,tool_use_id=identity,is_error=error,content=text)])))+'\n')
    def state(self):return monitor.read(self.db.parent/'monitor/state.json')
    def test_heartbeat_only_is_not_progress_and_identical_incident_notifies_once(self):
        self.check();self.append('beat',kind='tool_progress')
        result=self.check(901);self.assertEqual(result['findings'][0]['kind'],'stalled');self.assertEqual(len(self.sent),1)
        self.check(961);self.assertEqual(len(self.sent),1);self.assertNotIn(TOKEN,(self.db.parent/'monitor/state.json').read_text())
    def test_real_tool_result_resets_stall_clock_and_recovery_notifies_once(self):
        self.check();self.check(901);self.append('actual-result')
        result=self.check(960);self.assertEqual(result['findings'],[]);self.assertEqual(len(self.sent),2)
        self.check(1020);self.assertEqual(len(self.sent),2)
    def test_repeated_timeout_is_detected_even_with_intervening_reads(self):
        self.check()
        for i in range(1,4):
            self.append('error-'+str(i),True,'timed out after 240 seconds');self.append('read-'+str(i),False,'Read a diagnostic file');result=self.check(i*60)
        self.assertEqual(result['findings'][0]['kind'],'repeated-timeout');self.assertEqual(len(self.sent),1)
    def test_quoted_error_text_is_not_an_actual_tool_failure(self):
        self.check()
        for i in range(1,4):self.append(str(i),False,'1\tDocs: Command [example] timed out after 240 seconds');self.check(i*60)
        self.assertEqual(self.sent,[])
    def test_paused_stopped_and_expired_sessions_never_alert_or_resume(self):
        self.check()
        for status in ['paused','stopped','completed']:
            with self.server.store._connect() as c:c.execute('UPDATE automatic_sessions SET status=? WHERE id=?',(status,self.session['id']))
            self.assertEqual(self.check(1000)['active_sessions'],0)
        with self.server.store._connect() as c:c.execute("UPDATE automatic_sessions SET status='running' WHERE id=?",(self.session['id'],))
        self.assertEqual(self.check(4000)['active_sessions'],0);self.assertEqual(self.sent,[])
    def test_valid_long_experiment_is_not_stalled_but_overdue_record_is_flagged(self):
        with sqlite3.connect(self.db) as c:c.execute('INSERT INTO experiment_runs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',('run-fixture','plan-fixture','approval-fixture',self.pid,'epoch','running',1800,now(),now(),None,None,None,str(self.folder),'{}',None))
        self.check();self.assertEqual(self.check(901)['findings'],[])
        result=self.check(1921);self.assertIn('experiment-overdue',[v['kind'] for v in result['findings']])
    def test_backend_failure_requires_three_checks_and_monitor_does_not_change_research(self):
        before=self.server.autopilot.get(self.session['id'])
        self.assertEqual(self.check(0,probe=lambda *args:False)['findings'],[])
        self.assertEqual(self.check(60,probe=lambda *args:False)['findings'],[])
        result=self.check(120,probe=lambda *args:False);self.assertEqual(result['findings'][0]['kind'],'backend-down')
        self.assertEqual(self.server.autopilot.get(self.session['id']),before);self.assertEqual(result['model_calls'],0)
    def test_ambiguous_slack_send_is_not_replayed(self):
        self.check();self.check(901,sender=lambda *args:('uncertain',0))
        self.check(961,sender=lambda *args:self.fail('Must not repeat uncertain Slack send'))
        self.assertEqual(self.state()['outbox'][0]['state'],'uncertain')
    def test_slack_429_waits_for_known_retry_after(self):
        self.check();self.check(901,sender=lambda *args:('pending',120))
        self.check(961,sender=lambda *args:self.fail('Retry is not due'))
        self.check(1022);self.assertEqual(len(self.sent),1)
    def test_muted_and_changed_slack_destinations_do_not_get_stale_alerts(self):
        self.check();self.check(901,notify=False)
        root=self.db.parent/'integrations';creds=json.loads((root/'slack-credentials.json').read_text());creds['channel']='D9876543210';(root/'slack-credentials.json').write_text(json.dumps(creds))
        self.check(961);self.assertEqual(self.sent,[]);self.assertEqual(self.state()['outbox'][0]['state'],'cancelled')
    def test_observer_read_error_does_not_report_false_recovery(self):
        self.check();self.check(901)
        with patch('brain_monitor.inspect',side_effect=sqlite3.OperationalError('OFFLINE busy')):self.check(961)
        self.assertEqual(len(self.sent),1);self.assertTrue(next(iter(self.state()['incidents'].values()))['active'])
    def test_historical_failed_job_is_not_recounted_each_minute(self):
        self.check()
        with self.server.store._connect() as c:c.execute("UPDATE research_jobs SET state='failed',error='timed out after 240 seconds',updated_at=? WHERE id=?",(now(),self.job))
        for seconds in [60,120,180]:self.check(seconds)
        errors=self.state()['sessions'][self.session['id']]['errors'];self.assertEqual(len(errors),1)
    def test_cli_status_does_not_connect_or_start_backend(self):
        with patch('terminal.connect',side_effect=AssertionError('Independent status must not start backend')),contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(terminal.main(['monitor','status','--db',str(self.db),'--json']),0)
        self.assertEqual(json.loads(out.getvalue())['model_calls'],0)
    def test_launchagent_runs_isolated_short_checks_with_no_model_commands(self):
        plist=self.db.parent/'test-agent.plist'
        with patch('brain_monitor.sys.platform','darwin'),patch('brain_monitor.agent_path',return_value=plist),patch('brain_monitor.subprocess.run') as run:
            run.return_value.returncode=0;result=monitor.install(self.db,self.fixture.client.url)
        v=plistlib.loads(plist.read_bytes());self.assertEqual(v['StartInterval'],60);self.assertEqual(v['ProgramArguments'][1],'-I');self.assertIn('check',v['ProgramArguments'])
        self.assertNotIn('claude',str(v));self.assertNotIn('codex',str(v));self.assertEqual(result['mode'],'auto_recover')
        self.assertNotIn(TOKEN,plist.read_text());self.assertEqual((self.db.parent/'monitor/brain_monitor.py').stat().st_mode&0o777,0o600)
    def test_only_loopback_server_can_be_monitored(self):
        with self.assertRaises(ValueError):monitor.valid_server('https://example.com')

    def test_enabled_monitor_delegates_repair_without_a_model_in_the_monitor(self):
        monitor.save(self.db.parent/'monitor/config.json',dict(auto_repair=True));calls=[]
        self.check();result=self.check(901,repairer=lambda db,server,item:(calls.append(item) or dict(state='repair_queued')))
        self.assertEqual(len(calls),1);self.assertEqual(calls[0]['session'],self.session['id'])
        self.assertEqual(result['mode'],'auto_recover');self.assertEqual(result['model_calls'],0)
        with self.server.store._connect() as c:c.execute("UPDATE automatic_sessions SET status='paused' WHERE id=?",(self.session['id'],))
        self.check(1000,repairer=lambda *args:self.fail('Paused projects cannot request repair'))

    def test_backend_recovery_is_requested_only_after_three_failed_checks(self):
        monitor.save(self.db.parent/'monitor/config.json',dict(auto_repair=True));calls=[]
        opts=dict(probe=lambda *args:False,starter=lambda *args:(calls.append('restart') or dict(state='backend_restart_started')))
        self.check(0,**opts);self.check(60,**opts);self.assertFalse(calls)
        self.check(120,**opts);self.check(180,**opts);self.assertEqual(calls,['restart'])
