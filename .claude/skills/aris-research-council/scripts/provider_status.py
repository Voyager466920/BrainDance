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


GPT_PLANS = {
    'free':'ChatGPT Free', 'go':'ChatGPT Go', 'plus':'ChatGPT Plus',
    'pro':'ChatGPT Pro', 'prolite':'ChatGPT Pro Lite', 'promax':'ChatGPT Pro Max',
    'team':'ChatGPT Team', 'business':'ChatGPT Business', 'enterprise':'ChatGPT Enterprise',
    'edu':'ChatGPT Edu', 'edu_plus':'ChatGPT Edu Plus', 'edu_pro':'ChatGPT Edu Pro',
    'self_serve_business_prolite':'ChatGPT Business Pro Lite',
    'self_serve_business_usage_based':'ChatGPT Business (usage based)',
    'ent26':'ChatGPT Enterprise', 'enterprise_cbp_automation':'ChatGPT Enterprise (automation)',
    'enterprise_cbp_usage_based':'ChatGPT Enterprise (usage based)',
}
CLAUDE_PLANS = {'free':'Claude Free', 'pro':'Claude Pro', 'max':'Claude Max',
                 'team':'Claude Team', 'enterprise':'Claude Enterprise'}
CLAUDE_TIERS = {'default_claude_max_5x':('max','Claude Max 5×'),
                'default_claude_max_20x':('max','Claude Max 20×')}


def unknown_plan():
    return dict(plan=None, plan_label=None, plan_state='unavailable', plan_source=None,
                auth_label=None)


def codex_status(include_usage=True):
    result = dict(name='GPT', detail='Codex', connection='unknown', windows=[], usage_state='unavailable', **unknown_plan())
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
        if account.get('type')=='chatgpt':
            result['auth_label']='ChatGPT 계정'
            plan=account.get('planType')
            if isinstance(plan,str) and plan in GPT_PLANS:
                result.update(plan=plan,plan_label=GPT_PLANS[plan],plan_state='available',plan_source='Codex account/read')
        elif account.get('type')=='apiKey':
            result.update(auth_label='API 키',plan_state='not_applicable')
        elif account.get('type')=='amazonBedrock':
            result.update(auth_label='Amazon Bedrock',plan_state='not_applicable')
        if not include_usage:
            return result
        try:
            quotas = call(3, 'account/rateLimits/read')
        except Exception:
            # A quota failure must not discard a successfully read account plan.
            return result
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


def claude_status(include_usage=True):
    result = dict(name='Claude', connection='unknown', windows=[], usage_state='unavailable', **unknown_plan())
    auth = subprocess.run(['claude', 'auth', 'status', '--json'], capture_output=True, text=True, timeout=8)
    if auth.returncode:
        return result
    auth_data = json.loads(auth.stdout)
    logged_in = auth_data.get('loggedIn')
    result['connection'] = 'authenticated' if logged_in else 'signed_out'
    if not logged_in:
        return result
    subscription=auth_data.get('subscriptionType')
    if isinstance(subscription,str) and subscription in CLAUDE_PLANS:
        result.update(plan=subscription,plan_label=CLAUDE_PLANS[subscription],plan_state='available',
                      plan_source='Claude auth status',auth_label='Claude 계정')
    method=auth_data.get('authMethod')
    if method in {'api_key','apiKey','console'}:
        result.update(auth_label='API / Console',plan=None,plan_label=None,plan_state='not_applicable',plan_source=None)
        return result
    if method=='claude.ai':result['auth_label']='Claude 계정'
    if auth_data.get('apiProvider') not in {None,'firstParty'}:
        result.update(auth_label='외부 API 제공사',plan=None,plan_label=None,plan_state='not_applicable',plan_source=None)
        return result
    try:
        credential = subprocess.run(['security', 'find-generic-password', '-s', 'Claude Code-credentials', '-w'],
                                    capture_output=True, text=True, timeout=8)
    except (OSError,subprocess.TimeoutExpired):
        return result
    if credential.returncode:
        return result
    try:
        oauth = json.loads(credential.stdout).get('claudeAiOauth', {})
        if not isinstance(oauth,dict):return result
    except (ValueError,AttributeError):
        return result
    tier=oauth.get('rateLimitTier')
    detail=CLAUDE_TIERS.get(tier) if isinstance(tier,str) else None
    if method=='claude.ai' and detail and subscription==detail[0] and oauth.get('subscriptionType')==subscription:
        result.update(plan_label=detail[1],plan_source='Claude auth status + OAuth plan metadata')
    if not include_usage:
        return result
    token = oauth.get('accessToken')
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
    except (urllib.error.URLError,TimeoutError,OSError):
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

    def report_snapshot(self):
        return self.get()

    def get(self, force=False):
        with self.lock:
            now = time.time()
            pending = [(key, fn) for key, fn in [('gpt', codex_status), ('claude', claude_status)]
                       if force or self.cache.get(key, {}).get('next_check', 0) <= now]
            def fetch(item):
                key, fn = item
                cached=self.cache.get(key,{})
                backoff=cached.get('next_check',0)>now and cached.get('value',{}).get('usage_state')=='rate_limited'
                try:
                    value = fn(include_usage=False) if backoff else fn()
                    if backoff and value.get('connection')=='authenticated' and value.get('plan_state')!='not_applicable':
                        value.update(usage_state='rate_limited',http_status=429)
                except Exception:
                    # Never include exception text: HTTP/subprocess errors can contain credentials.
                    value = dict(name='GPT' if key == 'gpt' else 'Claude', connection='unknown',
                                 windows=[], usage_state='unavailable', **unknown_plan())
                value['checked_at'] = datetime.now(timezone.utc).isoformat()
                next_check=cached['next_check'] if backoff else now+(300 if value['usage_state']=='rate_limited' else 60)
                return key, value, next_check
            with ThreadPoolExecutor(max_workers=2) as pool:
                for key, value, next_check in pool.map(fetch, pending):
                    self.cache[key] = dict(value=value, next_check=next_check)
            return {'providers': [self.cache[k]['value'] for k in ('gpt', 'claude')],
                    'scope': 'account_quota', 'refresh_seconds': 60}
