"""Evidence-backed pre-experiment rejection, distinct from measured completion."""
import hashlib
from pathlib import Path
from urllib.parse import urlsplit

import council
import steering
from tree_store import now

REJECTION_SKILLS={'research-pipeline','idea-discovery','novelty-check'}
KINDS={'duplicate','low_novelty','infeasible'}


def reject(server,job,session,rows,payload):
    from native_pipeline import session_skill_receipts,workspace,retain_brief
    config=job['config'];work=workspace(config)
    if config.get('task_role')!='study' or not config.get('hypothesis_task_id'):raise ValueError('독립 가설 연구에서만 실험 전 기각을 기록할 수 있습니다.')
    if rows:raise ValueError('이미 실행한 실험이 있습니다. 실험 전 기각으로 측정 결과를 대체할 수 없습니다.')
    kind=payload.get('rejection_kind');reason=payload.get('reason','')
    if kind not in KINDS or not isinstance(reason,str) or not 10<=len(reason.strip())<=3000:raise ValueError('기각 유형과 구체적인 사유를 기록하세요.')
    if not REJECTION_SKILLS<=session_skill_receipts(config)[0]:raise ValueError('공식 연구·아이디어·신규성 Skills의 실제 호출이 필요합니다.')
    reviewfile=work/'reviewer-latest.json'
    if not reviewfile.is_file() or reviewfile.is_symlink():raise ValueError('기각 전 기존 독립 Reviewer의 검토가 필요합니다.')
    review=council.read_json(reviewfile);receipt=Path(review.get('receipt','')).resolve()
    managed=(Path(server.store.db_path).parent/'council-runs').resolve()
    if not receipt.is_relative_to(managed) or receipt.parent.parent.name!='native-reviewer' or receipt.name!='usage.json' or not receipt.is_file():raise ValueError('실제 독립 Reviewer 실행 기록이 필요합니다.')
    usage=council.read_json(receipt)
    if usage.get('provider')!='openai' or not usage.get('thread_id'):raise ValueError('독립 Reviewer의 실제 모델 사용 기록이 필요합니다.')
    expected=dict(hypothesis_task_id=config['hypothesis_task_id'],native_cycle=config.get('native_cycle',0),direction_revision=steering.snapshot(server.store,job['project_id'])['revision'])
    if any(review.get(k)!=v for k,v in expected.items()) or review.get('run_ids')!=[]:raise ValueError('현재 가설·연구 방향에 대한 실험 전 Reviewer 검토가 필요합니다.')
    response=receipt.with_name('response.txt')
    if not response.is_file() or council.parse_object(response.read_text())!=review.get('review'):raise ValueError('Reviewer 원본 응답과 검토 기록이 일치하지 않습니다.')
    decision=review['review']
    if decision.get('disposition')!='reject' or decision.get('rejection_kind')!=kind or not isinstance(decision.get('rationale'),str) or len(decision['rationale'].strip())<10:raise ValueError('독립 Reviewer가 같은 사유로 명시적으로 기각해야 합니다.')
    urls=decision.get('evidence_urls',[])
    if not isinstance(urls,list) or any(not isinstance(u,str) or len(u)>2000 or urlsplit(u).scheme not in {'http','https'} or not urlsplit(u).netloc for u in urls):raise ValueError('기각 근거의 논문 URL을 확인하세요.')
    if kind in {'duplicate','low_novelty'} and not urls:raise ValueError('중복·신규성 기각에는 비교한 선행연구 URL이 필요합니다.')
    report=Path(payload['report'])
    if report.is_symlink() or not report.resolve().is_relative_to(work) or not report.is_file() or not report.read_text().strip():raise ValueError('현재 가설의 기각 보고서를 작성하세요.')
    node=server.store.get_node(job['node_id']);reason=reason.strip()
    text=report.read_text()+'\n\n## 실험 전 기각 기록\n\n'+reason+'\n\n실험을 실행하지 않았으며 측정 결과는 없습니다.\n\n### 독립 검토 근거\n\n'+decision['rationale']+'\n\n'+'\n'.join(urls)+'\n'
    root=Path(job['run_dir']);archive=root/'native-summary.md';archive.write_text(text)
    record=dict(job_id=job['id'],auto_session_id=session['id'],hypothesis_task_id=config['hypothesis_task_id'],outcome='rejected',rejection_kind=kind,reason=reason,reviewer_receipt=str(receipt),evidence_urls=urls,run_ids=[],measured=False,report=str(archive),report_sha256=hashlib.sha256(text.encode()).hexdigest(),completed_at=now())
    council.dump(root/'research-brief.json',dict(problem=node['title'],approach='실험 전 선행연구와 연구 타당성을 독립 검토했습니다.',findings='기각: '+reason+' 실험 실행 및 측정 결과는 없습니다.',limitations=['실험으로 성능이나 가설의 참·거짓을 검증한 결과가 아닙니다.'],next_steps=['다음 가설 또는 새로운 문제 탐색을 계속합니다.']))
    server.store.update_node(node['id'],status='discarded',metadata=dict(research_outcome=record))
    server.store.add_note(node['id'],'analysis','가설 기각 보고',text[:99000]);retain_brief(server,job)
    council.dump(work/'native-completion.json',record)
    return record
