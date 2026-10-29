"""Account allowance snapshots and percentage-point stop conditions; no model calls."""
from datetime import datetime,timezone
import math
import time
from zoneinfo import ZoneInfo

MAX_AGE=180


def snapshot(status):
    providers=[]
    for p in status.get('providers',[]):
        windows=[]
        for w in p.get('windows',[]):
            used=w.get('used_percent')
            if type(used) not in (int,float) or not math.isfinite(used):continue
            windows.append(dict(minutes=w.get('minutes'),remaining_percent=max(0,min(100,100-used)),resets_at=w.get('resets_at')))
        providers.append(dict(name=p.get('name'),connection=p.get('connection'),usage_state=p.get('usage_state'),checked_at=p.get('checked_at'),windows=windows))
    return dict(scope='account_allowance_percent',providers=providers)


def available(provider):
    try:age=time.time()-datetime.fromisoformat(provider['checked_at'].replace('Z','+00:00')).timestamp()
    except (KeyError,TypeError,ValueError):return False
    return provider.get('usage_state')=='available' and bool(provider.get('windows')) and -60<=age<=MAX_AGE


def parse_drop(text):
    try:value=int(text)
    except (TypeError,ValueError):raise ValueError('사용량 감소폭은 1–100%p의 정수로 입력하세요.')
    if not 1<=value<=100:raise ValueError('사용량 감소폭은 1–100%p로 입력하세요.')
    return value


def capture(status,drop):
    if type(drop) is not int or not 1<=drop<=100:raise ValueError('사용량 감소 한도는 1–100%p로 입력하세요.')
    baseline=snapshot(status)
    for name in ['GPT','Claude']:
        p=next((p for p in baseline['providers'] if p['name']==name),{})
        if not available(p):
            if p.get('connection') in {'connected','authenticated'} and p.get('usage_state')=='rate_limited':raise ValueError(name+' 로그인은 연결되어 있습니다. 사용량 조회 제한(HTTP 429)으로 감소 기준을 계산할 수 없습니다. 잠시 후 다시 시도하거나 사용량 보호를 끄고 시간 기준으로 실행하세요.')
            raise ValueError(name+'의 최신 잔여 사용량을 확인할 수 없습니다. 계정 상태를 갱신하거나 사용량 보호를 끄고 시간 기준으로 실행하세요.')
        if any(w['remaining_percent']<=0 for w in p['windows']):raise ValueError(name+'의 계정 사용량 한도를 소진했습니다.')
    return dict(basis='percentage_points_from_start',drop_percent=drop,baseline=baseline)


def evaluate(guard,current):
    """A quota reset never moves the original stop line or refunds session history."""
    for start in guard['baseline']['providers']:
        p=next((p for p in current['providers'] if p['name']==start['name']),{})
        if not available(p):return dict(stop=True,reason=start['name']+' 잔여 사용량 확인 불가 · 사용량 보호로 중지',kind='unavailable')
        for w in start['windows']:
            threshold=max(0,w['remaining_percent']-guard['drop_percent'])
            latest=next((v for v in p['windows'] if v['minutes']==w['minutes']),None)
            if latest is None:return dict(stop=True,reason=start['name']+' 사용량 구간 확인 불가 · 사용량 보호로 중지',kind='unavailable')
            if latest['remaining_percent']<=threshold:
                return dict(stop=True,kind='quota_drop',provider=start['name'],minutes=w['minutes'],start_remaining=w['remaining_percent'],remaining=latest['remaining_percent'],stop_at=threshold,reason=f"{start['name']} {window_name(w['minutes'])} 잔여 {latest['remaining_percent']:g}% · 시작 {w['remaining_percent']:g}%에서 {guard['drop_percent']}%p 감소 기준 도달")
    return dict(stop=False)


def window_name(minutes):
    if minutes==10080:return '주간'
    if minutes==300:return '5시간'
    return str(minutes)+'분' if minutes else '사용량 구간'


def describe(value,guard=None):
    lines=[]
    for name in ['GPT','Claude']:
        p=next((p for p in (value or {}).get('providers',[]) if p['name']==name),{})
        if not available(p):lines.append(name+': 잔여 사용량 확인 불가');continue
        start=next((v for v in (guard or {}).get('baseline',{}).get('providers',[]) if v['name']==name),{})
        parts=[]
        for w in p['windows']:
            text=f"{window_name(w['minutes'])} 잔여 {w['remaining_percent']:g}%"
            baseline=next((v for v in start.get('windows',[]) if v['minutes']==w['minutes']),None)
            if baseline:text+=f" (시작 {baseline['remaining_percent']:g}% → 중지 {max(0,baseline['remaining_percent']-guard['drop_percent']):g}%)"
            parts.append(text)
        lines.append(name+': '+' · '.join(parts))
    stamps=[p.get('checked_at') for p in (value or {}).get('providers',[]) if p.get('checked_at')]
    if stamps:
        try:stamp=datetime.fromisoformat(max(stamps).replace('Z','+00:00')).astimezone(ZoneInfo('Asia/Seoul')).strftime('%Y-%m-%d %H:%M:%S KST')
        except ValueError:stamp=max(stamps)
        lines.append('조회 시각: '+stamp)
    return '\n'.join(lines)+'\n계정에서 제공하는 사용량 한도의 잔여율입니다. 정확한 잔여 토큰 수는 제공되지 않습니다.'
