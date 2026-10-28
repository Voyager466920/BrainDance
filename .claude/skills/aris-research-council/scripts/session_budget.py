"""Cross-process admission accounting for one automatic research session.

Token estimates admit calls; actual provider usage can exceed an estimate.
An interrupted reservation remains charged, preventing silent budget refunds.
"""
import json
from pathlib import Path
import fcntl
from datetime import datetime,timezone

MAX_TOKEN_BUDGET=1_000_000_000
MAX_MODEL_CALLS=300


def update(path,operation,**values):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.with_suffix('.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        data=json.loads(path.read_text())
        if operation=='check':
            if data['calls']>=data['max_calls'] or sum(data['charges'].values())>=data['token_budget']:raise RuntimeError('자동모드 모델 호출 또는 토큰 한도를 소진했습니다.')
            return data
        if operation=='limits':
            calls=values['max_calls'];tokens=values['token_budget']
            if type(calls) is not int or not data['max_calls']<=calls<=MAX_MODEL_CALLS:raise ValueError('현재 호출 한도 이상, 최대 '+str(MAX_MODEL_CALLS)+'회로 설정하세요.')
            if type(tokens) is not int or not data['token_budget']<=tokens<=MAX_TOKEN_BUDGET:raise ValueError('현재 토큰 한도 이상, 최대 '+format(MAX_TOKEN_BUDGET,',')+'으로 설정하세요.')
            before=dict(max_calls=data['max_calls'],token_budget=data['token_budget'])
            data['max_calls']=calls;data['token_budget']=tokens
            data.setdefault('limit_changes',[]).append(dict(at=datetime.now(timezone.utc).isoformat(),before=before,after=dict(max_calls=calls,token_budget=tokens),calls_used=data['calls']))
        elif operation=='reserve':
            if data['calls']+values['calls']>data['max_calls']:raise RuntimeError('자동모드 모델 호출 한도를 소진했습니다.')
            if sum(data['charges'].values())+values['estimate']>data['token_budget']:raise RuntimeError('자동모드 토큰 예상 한도를 소진했습니다.')
            data['calls']+=values['calls'];data['charges'][values['key']]=data['charges'].get(values['key'],0)+values['estimate']
        elif operation=='record':
            # Includes parallel native subagents: don't release a reserved estimate.
            data['charges'][values['key']]=max(data['charges'].get(values['key'],0),values['tokens'])
            data.setdefault('observed',{})[values['key']]=values['tokens']
        else:raise ValueError('Unknown session budget operation')
        temp=path.with_suffix('.tmp');temp.write_text(json.dumps(data));temp.replace(path)
        return data
