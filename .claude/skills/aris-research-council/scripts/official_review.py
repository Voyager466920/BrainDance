"""Receipts for the unmodified ARIS review Skill; never a review orchestrator.

ARIS drives every round, fix, experiment and termination. This adapter only
executes its canonical helper and prevents the host from accepting an unfinished
loop. Thresholds and transition policy belong exclusively to upstream ARIS.
"""
import json
from pathlib import Path
import re
import subprocess
import time

import council


def assessment(job,text,required=True):
    from research_verdict import extract
    scientific=extract(text)
    try:
        value=council.parse_object(text)
        if isinstance(value,dict) and ('score' in value or not required):
            if scientific:value['research_assessment']=scientific
            return value
    except ValueError:pass
    try:
        from paper_verification import upstream
        module,_=upstream(Path(job['aris_repo'])/'tools/review_gate.py')
        score,verdict=module._parse_native_assessment(text)
        result=dict(review=text,score=score,verdict=verdict)
        if scientific:result['research_assessment']=scientific
        return result
    except Exception:
        if required:raise ValueError('원본 Reviewer 응답의 Score/Verdict를 확인할 수 없습니다. 원문을 유지하고 원본 출력 형식으로 결과 검토하세요.')
        return dict(review=text)


def state(work):
    work=Path(work)
    path=work/'review-stage/REVIEW_STATE.json'
    if not path.is_file():path=work/'REVIEW_STATE.json'
    return council.read_json(path) if path.is_file() else {}


def binding(job):
    return {key:job.get(key,default) for key,default in [('auto_session_id',None),('native_cycle',0),('hypothesis_task_id',None)]}


def rounds(job):
    path=Path(job['native_workspace'])/'native-review-rounds.jsonl'
    records=[json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.is_file() else []
    return [r for r in records if r['binding']==binding(job)]


def validate_round(args):
    run_id=args.get('review_run_id');number=args.get('review_round')
    if not isinstance(run_id,str) or not run_id.strip() or type(number) is not int or number<1:
        raise ValueError('원본 auto-review-loop의 run_id와 round를 review_run_id/review_round로 전달하세요. 원본 상태와 측정 결과를 유지해 같은 라운드를 이어가세요.')
    return run_id,number


def record_review(job,args,context,folder,result):
    """Bind the original Skill's run/round to an actual completed MCP response."""
    run_id,number=validate_round(args)
    record=dict(binding=binding(job),run_id=run_id,round=number,receipt=str(Path(folder)/'usage.json'),
                run_ids=[r['id'] for r in context['completed_runs']],direction_revision=context['revision'],review=result)
    with (Path(job['native_workspace'])/'native-review-rounds.jsonl').open('a') as output:
        output.write(json.dumps(record,ensure_ascii=False)+'\n')
    return record


def helper(job,tool,values):
    """Execute installed official code, retaining its complete output and exit state."""
    work=Path(job['native_workspace']);script=work/'.aris-official/tools'/tool
    upstream=Path(job['aris_repo'])/'tools'/tool
    if not script.is_file() or not upstream.is_file() or script.read_bytes()!=upstream.read_bytes():
        raise ValueError('REVIEW_UNAVAILABLE: 설치된 원본 ARIS 도구가 없거나 변경되었습니다: '+tool)
    command=['/bin/bash',str(script)] if tool=='save_trace.sh' else council.python_command(script)
    result=subprocess.run(command+values,cwd=work,capture_output=True,text=True,timeout=180)
    logs=Path(job['run_dir'])/'native-helpers'/str(time.time_ns());logs.mkdir(parents=True)
    (logs/'stdout.log').write_text(result.stdout);(logs/'stderr.log').write_text(result.stderr)
    council.dump(logs/'request.json',dict(helper=tool,args=values,returncode=result.returncode,source=str(script)))
    if tool=='review_gate.py' and result.returncode==0:
        records=rounds(job)
        if not records:raise ValueError('REVIEW_UNAVAILABLE: 원본 라운드에 연결된 실제 결과 Reviewer 기록이 없습니다.')
        latest=records[-1];review=latest['review']
        def option(name,default=None):
            return values[values.index(name)+1] if name in values else default
        if option('--round-backend')!='codex' or float(option('--score'))!=review.get('score') or option('--verdict')!=review.get('verdict'):
            raise ValueError('REVIEW_UNAVAILABLE: gate 입력은 실제 Codex 결과 검토의 score/verdict와 같아야 합니다.')
        council.dump(logs/'review-binding.json',latest)
        council.dump(work/'native-review-gate.json',dict(binding=binding(job),review_receipt=latest['receipt'],raw_logs=str(logs)))
        with (work/'native-review-gates.jsonl').open('a') as output:
            output.write(json.dumps(dict(review=latest,raw_logs=str(logs)))+'\n')
    if tool=='idea_discovery_gate.py' and result.returncode==0:
        from official_workflow import digests
        council.dump(work/'native-discovery-gate.json',dict(binding=binding(job),raw_logs=str(logs),artifacts=digests(work)))
    return dict(returncode=result.returncode,stdout=result.stdout[-24000:],stderr=result.stderr[-8000:],raw_logs=str(logs))


def completion(job,run_ids):
    """Validate PhE artifacts and original gate output, without generating a round."""
    work=Path(job['native_workspace']);current=state(work)
    records=rounds(job)
    if not current or not records:
        raise ValueError('원본 auto-review-loop가 아직 완료되지 않았습니다. REVIEW_STATE.json과 실제 라운드 기록을 남기고 원본 Phase A–E를 계속하세요. 기존 측정 결과는 재사용하세요.')
    selected=[r for r in records if r['run_id']==current.get('run_id')]
    number=current.get('round')
    if type(number) is not int or number<1 or {r['round'] for r in selected}!=set(range(1,number+1)):
        raise ValueError('원본 검토 round와 실제 라운드 호출 기록이 일치하지 않습니다. 코드 검토·Council은 결과 검토 라운드가 아닙니다.')
    latest=selected[-1]
    if latest['round']!=number or set(latest['run_ids'])!=set(run_ids) or not Path(latest['receipt']).is_file():
        raise ValueError('최신 실험 결과에 대한 원본 검토 라운드가 필요합니다.')
    gate_history=work/'native-review-gates.jsonl'
    gates=[json.loads(line)['review']['receipt'] for line in gate_history.read_text().splitlines()] if gate_history.is_file() else []
    last_per_round={r['round']:r for r in selected}
    if any(r['receipt'] not in gates for r in last_per_round.values()):
        raise ValueError('원본 review_gate.py는 완료된 각 결과 검토 라운드에 필요합니다.')
    raw=assessment(job,Path(latest['receipt']).with_name('response.txt').read_text())
    usage=council.read_json(latest['receipt'])
    if current.get('reviewer_backend','codex')!='codex' or not usage.get('thread_id') or current.get('threadId')!=usage['thread_id']:
        raise ValueError('원본 REVIEW_STATE에 실제 Codex Reviewer threadId를 유지하세요.')
    if raw!=latest['review'] or current.get('last_score')!=raw.get('score') or current.get('last_verdict')!=raw.get('verdict'):
        raise ValueError('원본 REVIEW_STATE의 점수·판정이 실제 Reviewer 응답과 다릅니다.')
    gate_path=work/'native-review-gate.json'
    gate=council.read_json(gate_path) if gate_path.is_file() else {}
    if gate.get('binding')!=binding(job) or gate.get('review_receipt')!=latest['receipt']:
        raise ValueError('원본 review_gate.py를 최신 결과 검토에 실행하세요. 판정 로직을 대신 만들지 마세요.')
    logs=Path(gate['raw_logs']);request=council.read_json(logs/'request.json')
    decision=json.loads((logs/'stdout.log').read_text())
    if request.get('helper')!='review_gate.py' or request.get('returncode')!=0:
        raise ValueError('REVIEW_UNAVAILABLE: 원본 gate 실행이 완료되지 않았습니다.')
    # Read the loop limit from the original Skill, not a second policy constant.
    original=Path(job['aris_repo'])/'skills/auto-review-loop/SKILL.md'
    installed=work/'.aris-official/skills/auto-review-loop/SKILL.md'
    if not original.is_file() or original.read_bytes()!=installed.read_bytes():
        raise ValueError('REVIEW_UNAVAILABLE: 원본 auto-review-loop Skill이 변경되었습니다.')
    match=re.search(r'(?m)^-\s+\*?\*?MAX_ROUNDS\s*=\s*(\d+)',installed.read_text())
    if not match:raise ValueError('REVIEW_UNAVAILABLE: 원본 Skill의 MAX_ROUNDS를 확인할 수 없습니다.')
    maximum=int(match[1]);positive=decision.get('decision')=='stop'
    if decision.get('decision') not in {'stop','continue'} or number>maximum or (not positive and number<maximum):
        raise ValueError('원본 ARIS 판정: '+str(decision.get('decision'))+' · '+str(number)+'/'+str(maximum)+'라운드. 원본 Skill에 따라 수정·실험·재검토를 계속하세요. 한도 종료 시에는 중단 상태로 보존하며 연구 완료로 처리하지 않습니다.')
    if current.get('status')!='completed' or current.get('pending_experiments'):
        raise ValueError('원본 Phase E를 완료하고 REVIEW_STATE.status=completed 및 미완료 실험을 확인하세요.')
    for name in ['AUTO_REVIEW.md','REVIEWER_MEMORY.md']:
        path=work/'review-stage'/name
        if name=='AUTO_REVIEW.md' and not path.is_file():path=work/name
        if not path.is_file() or not path.read_text().strip():raise ValueError('원본 검토 기록이 필요합니다: '+name)
    return dict(run_id=current['run_id'],round=number,max_rounds=maximum,gate=decision,review_scope='report_readiness',
                research_assessment=latest['review'].get('research_assessment'),
                outcome='positive' if positive else 'max_rounds_unresolved',review_receipt=latest['receipt'],gate_receipt=str(logs))
