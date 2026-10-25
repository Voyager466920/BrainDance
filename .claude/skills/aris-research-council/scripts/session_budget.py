"""Cross-process admission accounting for one automatic research session.

Token estimates admit calls; actual provider usage can exceed an estimate.
An interrupted reservation remains charged, preventing silent budget refunds.
"""
import json
from pathlib import Path
import fcntl


def update(path,operation,**values):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.with_suffix('.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        data=json.loads(path.read_text())
        if operation=='reserve':
            if data['calls']+values['calls']>data['max_calls']:raise RuntimeError('자동모드 모델 호출 한도를 소진했습니다.')
            if sum(data['charges'].values())+values['estimate']>data['token_budget']:raise RuntimeError('자동모드 토큰 예상 한도를 소진했습니다.')
            data['calls']+=values['calls'];data['charges'][values['key']]=data['charges'].get(values['key'],0)+values['estimate']
        else:
            # Includes parallel native subagents: don't release a reserved estimate.
            data['charges'][values['key']]=max(data['charges'].get(values['key'],0),values['tokens'])
            data.setdefault('observed',{})[values['key']]=values['tokens']
        temp=path.with_suffix('.tmp');temp.write_text(json.dumps(data));temp.replace(path)
        return data
