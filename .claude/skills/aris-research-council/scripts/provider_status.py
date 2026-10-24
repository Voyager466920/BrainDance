"""Read account authentication and quota without starting an inference turn.

Secrets stay in process memory and are never returned, logged or persisted.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import math
import os
import queue
import signal
import subprocess
import threading
import time
import urllib.error
import urllib.request


def percentage(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return max(0, min(100, value))
    return None


def codex_status():
    result = dict(name='GPT', detail='Codex', connection='unknown', windows=[], usage_state='unavailable')
    process = subprocess.Popen(['codex', 'app-server', '--stdio'], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, start_new_session=True)
    inbox = queue.Queue()
    def read():
        for line in process.stdout:
            try:
                inbox.put(json.loads(line))
            except ValueError:
                pass
        inbox.put(None)
    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    deadline = time.monotonic() + 18
    def send(obj):
        process.stdin.write(json.dumps(obj) + '\n')
        process.stdin.flush()
    def call(number, method, params=None):
        send(dict(id=number, method=method, params=params or {}))
        while True:
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                raise TimeoutError()
            row = inbox.get(timeout=remaining)
            if row is None:
                raise RuntimeError('RPC closed')
            if row.get('id') == number:
                if 'error' in row:
                    raise RuntimeError('RPC failed')
                return row['result']
    try:
        call(1, 'initialize', {'clientInfo': {'name': 'braindance-status', 'version': '1.0'}})
        send({'method': 'initialized'})
        account = call(2, 'account/read', {'refreshToken': False}).get('account')
        result['connection'] = 'authenticated' if account else 'signed_out'
        if not account:
            return result
        quotas = call(3, 'account/rateLimits/read')
        limits = (quotas.get('rateLimitsByLimitId') or {}).get('codex') or quotas.get('rateLimits') or {}
        for key in ('primary', 'secondary'):
            window = limits.get(key)
            if not window:
                continue
            used = percentage(window.get('usedPercent'))
            result['windows'].append(dict(used_percent=used, minutes=window.get('windowDurationMins'),
                                           resets_at=window.get('resetsAt')))
        result['connection'] = 'connected'
        result['usage_state'] = 'available' if any(w['used_percent'] is not None for w in result['windows']) else 'unavailable'
        return result
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
        process.stdin.close()
        process.wait(timeout=3)
        reader.join(timeout=1)
        process.stdout.close()


def claude_status():
    result = dict(name='Claude', connection='unknown', windows=[], usage_state='unavailable')
    auth = subprocess.run(['claude', 'auth', 'status', '--json'], capture_output=True, text=True, timeout=8)
    if auth.returncode:
        return result
    logged_in = json.loads(auth.stdout).get('loggedIn')
    result['connection'] = 'authenticated' if logged_in else 'signed_out'
    if not logged_in:
        return result
    credential = subprocess.run(['security', 'find-generic-password', '-s', 'Claude Code-credentials', '-w'],
                                capture_output=True, text=True, timeout=8)
    if credential.returncode:
        return result
    token = json.loads(credential.stdout).get('claudeAiOauth', {}).get('accessToken')
    if not token:
        return result
    request = urllib.request.Request('https://api.anthropic.com/api/oauth/usage', headers={
        'Authorization': 'Bearer ' + token, 'anthropic-beta': 'oauth-2025-04-20', 'User-Agent': 'BrainDance/1'})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            data = json.load(response)
    except urllib.error.HTTPError as error:
        result['usage_state'] = 'rate_limited' if error.code == 429 else 'unavailable'
        result['http_status'] = error.code
        return result
    result['connection'] = 'connected'
    for key, minutes in [('five_hour', 300), ('seven_day', 10080)]:
        window = data.get(key)
        if isinstance(window, dict):
            result['windows'].append(dict(used_percent=percentage(window.get('utilization')),
                                          minutes=minutes, resets_at=window.get('resets_at')))
    result['usage_state'] = 'available' if any(w['used_percent'] is not None for w in result['windows']) else 'unavailable'
    return result


class ProviderStatus:
    def __init__(self):
        self.lock = threading.Lock()
        self.cache = {}

    def get(self):
        with self.lock:
            now = time.time()
            pending = [(key, fn) for key, fn in [('gpt', codex_status), ('claude', claude_status)]
                       if self.cache.get(key, {}).get('next_check', 0) <= now]
            def fetch(item):
                key, fn = item
                try:
                    value = fn()
                except Exception:
                    # Never include exception text: HTTP/subprocess errors can contain credentials.
                    value = dict(name='GPT' if key == 'gpt' else 'Claude', connection='unknown',
                                 windows=[], usage_state='unavailable')
                value['checked_at'] = datetime.now(timezone.utc).isoformat()
                return key, value
            with ThreadPoolExecutor(max_workers=2) as pool:
                for key, value in pool.map(fetch, pending):
                    self.cache[key] = dict(value=value, next_check=now+(300 if value['usage_state']=='rate_limited' else 60))
            return {'providers': [self.cache[k]['value'] for k in ('gpt', 'claude')],
                    'scope': 'account_quota', 'refresh_seconds': 60}
