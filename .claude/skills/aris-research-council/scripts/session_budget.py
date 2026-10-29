"""Cross-process admission accounting for one automatic research session.

Token estimates admit calls; actual provider usage can exceed an estimate.
An interrupted reservation remains charged, preventing silent budget refunds.
"""
import json
from pathlib import Path
import fcntl
import time
from datetime import datetime,timezone

MAX_TOKEN_BUDGET=1_000_000_000
MAX_MODEL_CALLS=300


class DeadlineExpired(RuntimeError):pass
class QuotaStopped(RuntimeError):pass


def deadline_for(config):
    data=json.loads(Path(config['session_budget']).read_text()) if config.get('session_budget') else config
    return data.get('deadline_epoch') if data.get('policy',data.get('execution_policy'))=='until_deadline' else None


def time_only(config):return deadline_for(config) is not None


def check(data):
    if data.get('quota_stop'):raise QuotaStopped(data['quota_stop']['reason'])
    if data.get('policy')=='until_deadline':
        if time.time()>=data['deadline_epoch']:raise DeadlineExpired('설정한 연구 종료 시각에 도달했습니다.')
    elif data['calls']>=data['max_calls'] or sum(data['charges'].values())>=data['token_budget']:raise RuntimeError('자동모드 모델 호출 또는 토큰 한도를 소진했습니다.')


def update(path,operation,**values):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.with_suffix('.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        data=json.loads(path.read_text())
        if operation=='check':
            check(data)
            return data
        if operation=='time_only':
            end=values['deadline_epoch']
            if isinstance(end,bool) or not isinstance(end,(int,float)) or not time.time()<end<=time.time()+604800:raise ValueError('종료 시각은 지금부터 7일 안으로 지정하세요.')
            before={k:data.get(k) for k in ['policy','max_calls','token_budget','deadline_epoch']}
            data.update(policy='until_deadline',max_calls=None,token_budget=None,deadline_epoch=end,started_epoch=data.get('started_epoch',values.get('started_epoch',time.time())))
            data.setdefault('limit_changes',[]).append(dict(at=datetime.now(timezone.utc).isoformat(),before=before,after=dict(policy='until_deadline',deadline_epoch=end),calls_used=data['calls']))
        elif operation=='continue':
            end=values['deadline_epoch']
            if isinstance(end,bool) or not isinstance(end,(int,float)) or not time.time()<end<=time.time()+604800:raise ValueError('새 종료 시각을 확인하세요.')
            data.setdefault('continuations',[]).append(dict(at=datetime.now(timezone.utc).isoformat(),before=dict(deadline_epoch=data.get('deadline_epoch'),quota_stop=data.get('quota_stop'),policy=data.get('policy')),previous_config=values['previous_config'],previous_progress=values['previous_progress'],after=dict(deadline_epoch=end,quota_guard=values.get('quota_guard')),calls_used=data['calls'],observed_tokens=sum(data.get('observed',{}).values())))
            data.update(policy='until_deadline',deadline_epoch=end,window_started_epoch=values['started_epoch'],max_calls=None,token_budget=None)
            data.pop('quota_stop',None)
        elif operation=='quota_stop':
            data['quota_stop']=values
        elif operation=='limits':
            if data.get('policy')=='until_deadline':raise ValueError('시간 제한 모드입니다. 호출·토큰 제한 대신 종료 시각을 변경하세요.')
            calls=values['max_calls'];tokens=values['token_budget']
            if type(calls) is not int or not data['max_calls']<=calls<=MAX_MODEL_CALLS:raise ValueError('현재 호출 한도 이상, 최대 '+str(MAX_MODEL_CALLS)+'회로 설정하세요.')
            if type(tokens) is not int or not data['token_budget']<=tokens<=MAX_TOKEN_BUDGET:raise ValueError('현재 토큰 한도 이상, 최대 '+format(MAX_TOKEN_BUDGET,',')+'으로 설정하세요.')
            before=dict(max_calls=data['max_calls'],token_budget=data['token_budget'])
            data['max_calls']=calls;data['token_budget']=tokens
            data.setdefault('limit_changes',[]).append(dict(at=datetime.now(timezone.utc).isoformat(),before=before,after=dict(max_calls=calls,token_budget=tokens),calls_used=data['calls']))
        elif operation=='reserve':
            check(data)
            if data.get('policy')!='until_deadline':
                if data['calls']+values['calls']>data['max_calls']:raise RuntimeError('자동모드 모델 호출 한도를 소진했습니다.')
                if sum(data['charges'].values())+values['estimate']>data['token_budget']:raise RuntimeError('자동모드 토큰 예상 한도를 소진했습니다.')
            data['calls']+=values['calls'];data['charges'][values['key']]=data['charges'].get(values['key'],0)+values['estimate']
        elif operation=='correct_observation':
            key=values['key'];before=dict(observed=data.get('observed',{}).get(key),charged=data['charges'].get(key))
            data.setdefault('observed',{})[key]=values['tokens']
            data['charges'][key]=max(values['tokens'],min(data['charges'].get(key,0),50000))
            data.setdefault('anthropic_usage',{})[key]=values['breakdown']
            data.setdefault('usage_corrections',[]).append(dict(key=key,before=before,after=dict(observed=values['tokens'],charged=data['charges'][key]),reason=values['reason'],at=datetime.now(timezone.utc).isoformat()))
        elif operation=='record':
            # Includes parallel native subagents: don't release a reserved estimate.
            data['charges'][values['key']]=max(data['charges'].get(values['key'],0),values['tokens'])
            data.setdefault('observed',{})[values['key']]=values['tokens']
            if values.get('breakdown'):data.setdefault('anthropic_usage',{})[values['key']]=values['breakdown']
        else:raise ValueError('Unknown session budget operation')
        temp=path.with_suffix('.tmp');temp.write_text(json.dumps(data));temp.replace(path)
        return data
