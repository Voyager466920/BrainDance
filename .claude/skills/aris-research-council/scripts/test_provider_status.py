import json
import math
import subprocess
import unittest
import urllib.error
import io
from contextlib import contextmanager
from unittest.mock import patch

import provider_status as p


class ProviderTests(unittest.TestCase):
    @contextmanager
    def codex_rpc(self,account,quota=None,quota_error=False):
        rows=[dict(id=1,result={}),dict(id=2,result={'account':account})]
        rows.append(dict(id=3,error={'message':'PRIVATE_SECRET'}) if quota_error else dict(id=3,result=quota or {}))
        from unittest.mock import MagicMock
        process=MagicMock()
        process.stdin=io.StringIO()
        process.stdout=io.StringIO(''.join(json.dumps(r)+'\n' for r in rows))
        process.poll.return_value=0
        with patch.object(p.subprocess,'Popen',return_value=process):yield

    def test_percentage_missing_is_not_zero(self):
        self.assertEqual(p.percentage(0), 0)
        self.assertEqual(p.percentage(130), 100)
        for value in (None, True, '50', math.nan, math.inf):
            self.assertIsNone(p.percentage(value))

    def test_cache_respects_429_backoff_and_isolates_provider_failures(self):
        good = dict(name='GPT', connection='connected', windows=[], usage_state='available')
        limited = dict(name='Claude', connection='authenticated', windows=[], usage_state='rate_limited')
        with patch.object(p, 'codex_status', return_value=good) as g, patch.object(p, 'claude_status', return_value=limited) as c, patch.object(p.time, 'time', return_value=1000) as clock:
            status = p.ProviderStatus()
            status.get(); status.get()
            self.assertEqual(g.call_count, 1)
            self.assertEqual(c.call_count, 1)
            clock.return_value = 1061
            status.get()
            self.assertEqual(g.call_count, 2)
            self.assertEqual(c.call_count, 1)
            clock.return_value = 1301
            status.get()
            self.assertEqual(c.call_count, 2)
        with patch.object(p, 'codex_status', side_effect=RuntimeError('SECRET')), patch.object(p, 'claude_status', return_value=limited):
            self.assertNotIn('SECRET', json.dumps(p.ProviderStatus().get()))

    def test_claude_429_retains_auth_status_without_leaking_credentials(self):
        auth = subprocess.CompletedProcess([], 0, json.dumps({'loggedIn': True, 'email': 'PRIVATE_EMAIL', 'authMethod':'claude.ai', 'subscriptionType':'max'}))
        credential = subprocess.CompletedProcess([], 0, json.dumps({'claudeAiOauth': {'accessToken': 'PRIVATE_TOKEN','subscriptionType':'max','rateLimitTier':'default_claude_max_5x'}}))
        error = urllib.error.HTTPError('https://api.anthropic.com/api/oauth/usage', 429, 'limited', {}, None)
        with patch.object(p.subprocess, 'run', side_effect=[auth, credential]), patch.object(p.urllib.request, 'urlopen', side_effect=error):
            status = p.claude_status()
        self.assertEqual(status['connection'], 'authenticated')
        self.assertEqual(status['usage_state'], 'rate_limited')
        self.assertEqual(status['windows'], [])
        self.assertEqual(status['plan_label'],'Claude Max 5×')
        self.assertNotIn('PRIVATE', json.dumps(status))

    def test_codex_plan_and_quota_are_separate_without_returning_account_identity(self):
        account=dict(type='chatgpt',email='PRIVATE_EMAIL',planType='plus',accessToken='PRIVATE_TOKEN')
        quota={'rateLimits':{'primary':{'usedPercent':0,'windowDurationMins':300}}}
        with self.codex_rpc(account,quota):status=p.codex_status()
        self.assertEqual(status['plan_label'],'ChatGPT Plus')
        self.assertEqual(status['windows'][0]['used_percent'],0)
        self.assertNotIn('PRIVATE',json.dumps(status))
        with self.codex_rpc(account,quota_error=True):status=p.codex_status()
        self.assertEqual(status['plan_label'],'ChatGPT Plus')
        self.assertEqual(status['connection'],'authenticated')
        self.assertEqual(status['usage_state'],'unavailable')

    def test_codex_unknown_plan_api_auth_and_signed_out_are_not_guessed(self):
        for account,expected in [(dict(type='chatgpt',planType='future_PRIVATE_PLAN'),'unavailable'),(dict(type='apiKey'),'not_applicable'),(None,'unavailable')]:
            with self.codex_rpc(account):status=p.codex_status(include_usage=False)
            self.assertEqual(status['plan_state'],expected)
            self.assertIsNone(status['plan_label']);self.assertNotIn('PRIVATE',json.dumps(status))
        self.assertEqual(status['connection'],'signed_out')

    def test_claude_plan_survives_missing_keychain_and_offline_usage(self):
        auth=subprocess.CompletedProcess([],0,json.dumps(dict(loggedIn=True,authMethod='claude.ai',subscriptionType='pro')))
        with patch.object(p.subprocess,'run',side_effect=[auth,FileNotFoundError('security unavailable')]):
            self.assertEqual(p.claude_status()['plan_label'],'Claude Pro')
        credential=subprocess.CompletedProcess([],0,json.dumps({'claudeAiOauth':{'accessToken':'PRIVATE_TOKEN'}}))
        with patch.object(p.subprocess,'run',side_effect=[auth,credential]),patch.object(p.urllib.request,'urlopen',side_effect=urllib.error.URLError('PRIVATE_URL')):
            status=p.claude_status()
        self.assertEqual(status['plan_label'],'Claude Pro');self.assertNotIn('PRIVATE',json.dumps(status))

    def test_claude_tier_must_match_current_subscription(self):
        for subscription,tier,expected in [('max','default_claude_max_20x','Claude Max 20×'),('pro','default_claude_max_20x','Claude Pro'),('max','unknown_PRIVATE','Claude Max')]:
            auth=subprocess.CompletedProcess([],0,json.dumps(dict(loggedIn=True,authMethod='claude.ai',subscriptionType=subscription)))
            credential=subprocess.CompletedProcess([],0,json.dumps({'claudeAiOauth':{'subscriptionType':'max','rateLimitTier':tier}}))
            with patch.object(p.subprocess,'run',side_effect=[auth,credential]):status=p.claude_status(include_usage=False)
            self.assertEqual(status['plan_label'],expected);self.assertNotIn('PRIVATE',json.dumps(status))

    def test_claude_api_and_signed_out_do_not_read_subscription_credentials(self):
        for data,expected in [(dict(loggedIn=True,authMethod='api_key',subscriptionType='max'),'not_applicable'),(dict(loggedIn=False,subscriptionType='max'),'unavailable')]:
            auth=subprocess.CompletedProcess([],0,json.dumps(data))
            with patch.object(p.subprocess,'run',return_value=auth) as run:
                status=p.claude_status()
            self.assertEqual(run.call_count,1);self.assertEqual(status['plan_state'],expected);self.assertIsNone(status['plan_label'])

    def test_manual_refresh_reads_new_account_but_respects_usage_backoff(self):
        limited=dict(name='Claude',connection='authenticated',windows=[],usage_state='rate_limited',plan_label='Claude Pro',plan_state='available')
        new=dict(name='Claude',connection='authenticated',windows=[],usage_state='unavailable',plan_label='Claude Max',plan_state='available')
        good=dict(name='GPT',connection='authenticated',windows=[],usage_state='unavailable')
        with patch.object(p,'claude_status',side_effect=[limited,new,new]) as c,patch.object(p,'codex_status',return_value=good),patch.object(p.time,'time',return_value=1000) as clock:
            service=p.ProviderStatus();service.get();clock.return_value=1001
            response=service.get(force=True)
            self.assertEqual(response['providers'][1]['plan_label'],'Claude Max')
            self.assertEqual(response['providers'][1]['usage_state'],'rate_limited')
            c.assert_called_with(include_usage=False)
            self.assertEqual(service.cache['claude']['next_check'],1300)
            clock.return_value=1301;service.get()
            self.assertEqual(c.call_count,3)


if __name__ == '__main__':
    unittest.main()
