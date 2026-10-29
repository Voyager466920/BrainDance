"""Claude hook for local bookkeeping and original ARIS helper execution.

The original Skills/leaf run normally. Research execution still belongs to the
existing selected-resource broker, rather than an untracked shell/SSH process.
"""
import json
from pathlib import Path
import shlex
import sqlite3
import sys
import uuid


def decide(job,event):
    try:
        if event.get('tool_name')!='Bash':return {}
        if job.get('auto_session_id'):
            with sqlite3.connect(Path(job['db']).as_uri()+'?mode=ro',uri=True) as c:
                row=c.execute('SELECT status FROM automatic_sessions WHERE id=?',(job['auto_session_id'],)).fetchone()
            if not row or row[0]!='running':raise ValueError('프로젝트가 중지 또는 일시정지되었습니다.')
            from session_budget import update
            update(job['session_budget'],'check')
        command=event['tool_input']['command']
        if any(x in command for x in ['\n',';','&&','||','|','>','<','`','$','&']):
            raise ValueError('로컬 단일 명령 또는 helper(name,args)를 사용하세요. 실험·SSH 실행은 experiment 도구로 전달하세요.')
        tokens=shlex.split(command)
        if not tokens:raise ValueError('Empty command')
        work=Path(job['native_workspace']).resolve();repo=Path(job['aris_repo']).resolve()
        tool=Path(tokens[0]).name;updated=None
        if tool in {'python','python3','bash','sh'}:
            from native_pipeline import HELPERS,command as host_command
            if len(tokens)<2:raise ValueError('원본 helper 경로가 필요합니다.')
            script=(work/tokens[1]).resolve()
            if script.name not in HELPERS or script!=repo/'tools'/script.name:
                raise ValueError('원본 ARIS helper만 셸에서 실행합니다. 모델·실험 코드는 experiment 도구를 사용하세요.')
            request=work/'.host-helper-requests'/(uuid.uuid4().hex+'.json');request.parent.mkdir(exist_ok=True)
            request.write_text(json.dumps(dict(name=script.name,args=tokens[2:])))
            argv=host_command('--native-helper',str(Path(job['run_dir'])/'job.json'),str(request))
            updated={**event['tool_input'],'command':shlex.join(argv)}
        elif tool in {'pwd','date','mkdir','ls','head','tail','wc','stat','cat','shasum','sha256sum','git','test','['}:
            if tool=='git' and tokens[1:]!=['rev-parse','--show-toplevel']:raise ValueError('이 세션의 git 셸 명령은 루트 조회만 지원합니다.')
            for value in tokens[1:]:
                if value.startswith('-') or value.isdigit() or tool=='date':continue
                path=(work/Path(value).expanduser()).resolve()
                if not path.is_relative_to(work) and not path.is_relative_to(repo):raise ValueError('로컬 기록 명령은 현재 연구 작업공간과 원본 ARIS 경로에서 실행합니다.')
        else:raise ValueError('이 셸 명령은 연구 실행을 추적할 수 없습니다. 원본 절차는 유지하고 helper/target/experiment 도구를 사용하세요.')
        output=dict(hookEventName='PreToolUse',permissionDecision='allow')
        if updated:output['updatedInput']=updated
        return dict(hookSpecificOutput=output)
    except Exception as error:
        return dict(hookSpecificOutput=dict(hookEventName='PreToolUse',permissionDecision='deny',permissionDecisionReason=str(error)))


def main(jobfile):
    print(json.dumps(decide(json.loads(Path(jobfile).read_text()),json.load(sys.stdin)),ensure_ascii=False))
