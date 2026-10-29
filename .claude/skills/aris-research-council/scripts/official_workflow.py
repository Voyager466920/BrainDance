"""Require original discovery/refinement artifacts and an actual upstream gate run."""
from pathlib import Path
import hashlib
import council
from official_review import binding

ARTIFACTS=('idea-stage/IDEA_REPORT.md','refine-logs/FINAL_PROPOSAL.md',
           'refine-logs/EXPERIMENT_PLAN.md','refine-logs/EXPERIMENT_TRACKER.md')


def digests(work):
    return {name:hashlib.sha256((Path(work)/name).read_bytes()).hexdigest() for name in ARTIFACTS if (Path(work)/name).is_file()}


def plans(job):
    work=Path(job['native_workspace'])
    missing=[name for name in ARTIFACTS if not (work/name).is_file() or not (work/name).read_text().strip()]
    if missing:raise ValueError('원본 idea-discovery/research-refine-pipeline 산출물이 필요합니다: '+', '.join(missing)+'. 기존 측정은 보존하고 원본 하위 Skill에서 누락 단계를 수행하세요.')
    return list(ARTIFACTS)


def completed(job):
    artifacts=plans(job);work=Path(job['native_workspace']);path=work/'native-discovery-gate.json'
    if not path.is_file():raise ValueError('원본 idea_discovery_gate.py를 실제 실행해 탐색·신규성 리뷰·제안 정교화 증거를 검증하세요. Skill 호출만으로 완료되지 않습니다.')
    gate=council.read_json(path)
    if gate.get('artifacts')!=digests(work):raise ValueError('탐색·실험 계획이 바뀌었습니다. 최신 산출물로 원본 evidence gate를 다시 실행하세요.')
    logs=Path(gate.get('raw_logs',''));request=logs/'request.json'
    if gate.get('binding')!=binding(job) or not request.is_file():raise ValueError('현재 가설·사이클의 원본 탐색 gate 기록이 필요합니다.')
    receipt=council.read_json(request)
    if receipt.get('helper')!='idea_discovery_gate.py' or receipt.get('returncode')!=0:raise ValueError('원본 탐색 evidence gate가 통과하지 않았습니다.')
    return dict(artifacts=artifacts,gate_receipt=str(logs))
