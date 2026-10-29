"""Keep original idea-creator provenance; no replacement idea generation/jury."""
import json
from pathlib import Path

import council
from stream_records import blocks


def validate(job):
    from native_pipeline import session_skill_receipts
    invoked,sources,_=session_skill_receipts(job)
    if 'idea-creator' not in invoked:raise ValueError('원본 idea-creator Skill의 실제 성공 호출이 필요합니다.')
    work=Path(job['native_workspace']);report=work/'idea-stage/IDEA_REPORT.md'
    if not report.is_file() or not report.read_text().strip():raise ValueError('원본 idea-creator의 idea-stage/IDEA_REPORT.md가 필요합니다.')
    calls={};finished=set();notifications={};reviewer_receipts=[]
    for item in sources:
        for line in Path(item['trace']).read_text().splitlines():
            try:event=json.loads(line)
            except ValueError:continue
            if isinstance(event,dict) and event.get('type')=='system' and event.get('subtype')=='task_notification':
                notifications[event.get('tool_use_id')]=event.get('status')
            for block in blocks(event):
                if block.get('type')=='tool_use' and block.get('name')=='Agent':
                    args=block.get('input') or {}
                    if args.get('subagent_type','').split(':')[-1]=='aris-fanout-leaf':calls[block['id']]=dict(id=block['id'],input=args)
                if block.get('type')=='tool_result' and block.get('tool_use_id') in calls:
                    if not calls[block['tool_use_id']]['input'].get('run_in_background'):finished.add(block['tool_use_id'])
        reviewer_receipts.extend(str(p) for p in Path(item['trace']).parent.glob('native-reviewer/*/usage.json') if p.with_name('response.txt').is_file())
    if not calls:raise ValueError('원본 Phase 1.5의 aris-fanout-leaf 호출 기록이 없습니다. 원본 agent가 설치되어 있으며 Agent 도구를 사용할 수 있습니다.')
    pending=[key for key in calls if key not in finished and notifications.get(key) not in {'completed','failed','stopped'}]
    if pending:raise ValueError('원본 leaf 작업이 아직 실행 중입니다. 실제 종료와 coverage 기록을 확인하세요.')
    if not reviewer_receipts:raise ValueError('원본 Codex brainstorm/검토의 실제 응답 기록이 필요합니다.')
    from official_workflow import completed
    completed(job)
    receipt=dict(report=str(report),leaf_calls=list(calls.values()),leaf_notifications=notifications,reviewer_receipts=reviewer_receipts,source_jobs=sources,original_skill=str(Path(job['aris_repo'])/'skills/idea-creator/SKILL.md'))
    council.dump(Path(job['run_dir'])/'original-idea-creator-receipt.json',receipt)
    return receipt
