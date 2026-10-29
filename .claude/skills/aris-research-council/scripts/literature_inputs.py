"""Normalize explicit identifier aliases without discarding raw retrieval files."""
import hashlib
import json
from pathlib import Path
import re
import council


def aliases(paper):
    values=[]
    for key in ('id','canonical_id','arxiv_id','doi','url','abs_url'):
        value=paper.get(key)
        if not isinstance(value,str) or not value.strip():continue
        value=value.strip().lower()
        value=re.sub(r'^https?://(?:www\.)?arxiv.org/(?:abs|pdf)/','',value)
        value=re.sub(r'^https?://(?:dx\.)?doi.org/','',value)
        value=re.sub(r'^(arxiv|doi):','',value).removesuffix('.pdf')
        values.append(value)
    return set(values)


def normalize(work, root):
    work=Path(work);raw={name:(work/name).read_text() for name in ('LITERATURE.md','source-evidence.json','candidate_papers.json')}
    source=json.loads(raw['source-evidence.json']);candidates=json.loads(raw['candidate_papers.json'])
    papers=source.get('papers') if isinstance(source,dict) else source
    candidates=candidates.get('papers') if isinstance(candidates,dict) else candidates
    if not isinstance(papers,list) or not papers or len(papers)>20:raise ValueError('source-evidence.json의 papers에는 1–20개 논문 객체가 필요합니다.')
    if not isinstance(candidates,list) or len(candidates)>20:raise ValueError('candidate_papers.json은 배열 또는 {papers: 배열}이어야 합니다 (최대 20개).')
    if any(not isinstance(p,dict) for p in papers+candidates):raise ValueError('논문은 객체여야 합니다.')
    canonical=[];checked=[];used=set()
    for paper in papers:
        matches=[(i,p) for i,p in enumerate(candidates) if aliases(paper)&aliases(p)]
        if len(matches)!=1:raise ValueError('논문 식별자로 후보를 하나만 연결해야 합니다: '+str(sorted(aliases(paper))))
        i,candidate=matches[0];used.add(i);merged={**candidate,**paper}
        pid=paper.get('id') or candidate.get('id') or next(iter(sorted(aliases(paper))),None)
        if not isinstance(pid,str) or not pid:raise ValueError('논문 id 또는 canonical_id가 필요합니다.')
        merged['id']=pid
        merged['url']=merged.get('url') or merged.get('abs_url')
        merged['source_excerpt']=merged.get('source_excerpt') or merged.get('abstract') or merged.get('abstract_excerpt')
        for value in aliases(merged):
            if re.fullmatch(r'\d{4}\.\d{4,5}(v\d+)?',value) and not merged.get('arxiv_id'):merged['arxiv_id']=value
            if value.startswith('10.') and '/' in value and not merged.get('doi'):merged['doi']=value
        canonical.append(merged)
        checked.append({k:merged[k] for k in ('id','arxiv_id','doi','title') if merged.get(k)})
    if len({p['id'] for p in canonical})!=len(canonical):raise ValueError('논문 ID가 중복되었습니다.')
    digest=hashlib.sha256(json.dumps(raw,sort_keys=True).encode()).hexdigest()
    target=Path(root)/'normalized-literature'/digest;target.mkdir(parents=True,exist_ok=True)
    for name,text in raw.items():
        p=target/('raw-'+name)
        if not p.exists():p.write_text(text)
    council.dump(target/'source-evidence.json',dict(papers=canonical))
    council.dump(target/'candidate_papers.json',checked)
    (target/'LITERATURE.md').write_text(raw['LITERATURE.md'])
    council.dump(target/'normalization.json',dict(source=str(work),raw_digest=digest,excluded_candidates=[p for i,p in enumerate(candidates) if i not in used],verification='required; normalization does not verify existence or claims'))
    return target
