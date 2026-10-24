import json
import math
import subprocess
import unittest
import urllib.error
from unittest.mock import patch

import provider_status as p


class ProviderTests(unittest.TestCase):
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
        auth = subprocess.CompletedProcess([], 0, json.dumps({'loggedIn': True, 'email': 'PRIVATE_EMAIL'}))
        credential = subprocess.CompletedProcess([], 0, json.dumps({'claudeAiOauth': {'accessToken': 'PRIVATE_TOKEN'}}))
        error = urllib.error.HTTPError('https://api.anthropic.com/api/oauth/usage', 429, 'limited', {}, None)
        with patch.object(p.subprocess, 'run', side_effect=[auth, credential]), patch.object(p.urllib.request, 'urlopen', side_effect=error):
            status = p.claude_status()
        self.assertEqual(status['connection'], 'authenticated')
        self.assertEqual(status['usage_state'], 'rate_limited')
        self.assertEqual(status['windows'], [])
        self.assertNotIn('PRIVATE', json.dumps(status))


if __name__ == '__main__':
    unittest.main()
