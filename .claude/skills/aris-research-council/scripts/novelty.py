"""Fresh prior-art retrieval and existence checks using unmodified upstream tools.

A search receipt is evidence for review, never a proof of novelty. Raw responses,
failed source queries and the original verifier output are retained separately.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time


def key(idea):return hashlib.sha256(json.dumps(idea,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def queries_for(idea):
    queries=idea.get('novelty_queries') or [idea.get('title',''),idea.get('research_question',''),idea.get('hypothesis','')]
    if not isinstance(queries,list):raise ValueError('신규성 검색어는 문자열 목록이어야 합니다.')
    result=[]
    for query in queries:
        if isinstance(query,str) and query.strip():
            query=' '.join(query.split())[:400]
            if query not in result:result.append(query)
    if not result:raise ValueError('재검색할 연구 가설이나 검색어가 필요합니다.')
    return result[:3]


def helper(repo,name,args,folder,config):
    import council
    from session_budget import deadline_for
    folder.mkdir(parents=True,exist_ok=True);argv=council.python_command(Path(repo)/'tools'/name)+args
    council.dump(folder/'request.json',dict(helper=name,args=args,requested_at=time.time(),cache_bypassed='--no-cache' in args))
    end=deadline_for(config);timeout=min(120,max(.1,end-time.time())) if end else 120
    with (folder/'stdout.json').open('w') as out,(folder/'stderr.log').open('w') as err:
        process=subprocess.Popen(argv,stdout=out,stderr=err,start_new_session=True)
        with council.PROCESS_LOCK:council.ACTIVE_PROCESSES.add(process)
        try:
            try:code=process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:raise RuntimeError('논문 출처 조회 제한 시간 초과') from None
            if code:raise RuntimeError('공식 논문 도구 오류: '+str(code))
            return json.loads((folder/'stdout.json').read_text() or 'null')
        finally:
            if process.poll() is None:
                os.killpg(process.pid,signal.SIGTERM)
                try:process.wait(timeout=3)
                except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait()
            with council.PROCESS_LOCK:council.ACTIVE_PROCESSES.discard(process)


def canonical(paper):
    from scout import canonical as identity
    try:return identity(paper)
    except (ValueError,KeyError,TypeError):return ''


def audit(idea,folder,aris_repo,config=None,cited=None):
    import council
    config=config or {};folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    identity=key(idea);target=folder/'audit.json'
    if target.is_file():
        prior=council.read_json(target)
        if prior['idea_hash']!=identity:raise ValueError('다른 가설의 재검색 영수증을 재사용할 수 없습니다.')
        # A retry reuses this exact, already completed network operation. New scientific cycles use new folders.
        return prior
    queries=queries_for(idea);retrieved={};searches=[]
    for index,query in enumerate(queries):
        # No recency filter: old prior art is as relevant as a new preprint.
        for source,tool,args in [('openalex','openalex_fetch.py',['search',query,'--max','5','--json']),('arxiv','arxiv_fetch.py',['search',query,'--max','5'])]:
            from session_budget import update
            if config.get('session_budget'):update(config['session_budget'],'check')
            location=folder/('search-'+str(index+1)+'-'+source)
            try:
                papers=helper(aris_repo,tool,args,location,config)
                if not isinstance(papers,list):raise ValueError('논문 검색 결과는 목록이어야 합니다.')
                for paper in papers:
                    pid=canonical(paper)
                    if pid and paper.get('title'):retrieved.setdefault(pid,{**paper,'id':pid,'retrieval_source':source})
                searches.append(dict(query=query,source=source,status='retrieved',count=len(papers),raw=str(location)))
            except (ValueError,RuntimeError,OSError) as error:searches.append(dict(query=query,source=source,status='unavailable',error=str(error),raw=str(location)))
    # Check retrieved papers AND prior citations afresh; an old verified flag is never sufficient.
    papers=list(retrieved.values())[:16]
    for paper in cited or []:
        if isinstance(paper,dict) and paper.get('title') and len(papers)<20:
            pid=canonical(paper) or str(paper.get('id',''))
            if pid and pid not in {p['id'] for p in papers}:papers.append({**paper,'id':pid,'retrieval_source':'prior_citation'})
    candidates=[]
    for p in papers:
        arxiv=p.get('arxiv_id') or (p['id'].split(':',1)[1] if p['id'].startswith('arxiv:') else None)
        doi=p.get('doi');doi=re.sub(r'^https?://(?:dx\.)?doi\.org/','',doi) if isinstance(doi,str) else None
        candidates.append(dict(id=p['id'],title=p['title'],arxiv_id=arxiv,doi=doi))
    council.dump(folder/'candidate_papers.json',candidates);checks={};verification_error=None
    if candidates:
        try:
            helper(aris_repo,'verify_papers.py',['--input',str((folder/'candidate_papers.json').resolve()),'--output',str((folder/'verification.json').resolve()),'--no-cache','--cache-dir',str((folder/'identity-cache').resolve())],folder/'existence-check',config)
            checks={p['id']:p for p in council.read_json(folder/'verification.json')['papers']}
        except (ValueError,RuntimeError,OSError,KeyError) as error:verification_error=str(error)
    verified=[];pending=[]
    for paper in papers:
        check=checks.get(paper['id'],{});item={**paper,'verification_status':check.get('status','verify_pending'),'verification_method':check.get('method'),'identity_scope':'Identifier existence only; not validation of claims, title-to-ID equivalence or novelty.'}
        # Only fresh source-returned metadata enters the review evidence. Prior citations not re-retrieved stay uncertain.
        if item['verification_status']=='verified' and item['retrieval_source']!='prior_citation':verified.append(item)
        else:pending.append(item)
    result=dict(idea=idea,idea_hash=identity,checked_at=time.time(),queries=queries,searches=searches,papers=verified,unverified_papers=pending,verification_error=verification_error,retrieved_count=len(retrieved),omitted_retrieved_count=max(0,len(retrieved)-16),
                search_status='searched' if any(s['status']=='retrieved' for s in searches) else 'unavailable',novelty_status='unverified',
                limitation='Fresh search and identifier existence are not novelty proof. Compare the actual mechanisms and closest prior work. Abstract-only/missing evidence must remain uncertain; no-result searches cannot prove novelty.',receipt=str(target.resolve()))
    council.dump(target,result);return result


def review_context(receipt,limit=14000):
    # Keep the original full evidence/diagnostics on disk; this is a bounded model excerpt.
    papers=[];used=0
    for p in receipt['papers']:
        item={k:p.get(k) for k in ['id','title','doi','arxiv_id','url','abs_url','verification_status']}
        item['excerpt']=str(p.get('abstract') or p.get('source_excerpt') or '')[:1600]
        item['coverage']='abstract excerpt only' if item['excerpt'] else 'metadata only; claims not verified'
        size=len(json.dumps(item,ensure_ascii=False))
        if used+size>limit:break
        used+=size;papers.append(item)
    return json.dumps(dict(fresh_queries=receipt['queries'],search_status=receipt['search_status'],verified_prior_art=papers,unverified_ids=[p['id'] for p in receipt['unverified_papers']],omitted_verified_count=len(receipt['papers'])-len(papers),limitation=receipt['limitation']),ensure_ascii=False)


def round_checks(blind,folder,repo,config):
    records={}
    for label,idea in blind.items():records[label]=audit(idea,Path(folder)/key(idea),repo,config)
    return records


def calibrated(assessment,receipt):
    result=dict(assessment);ids={p['id'] for p in receipt['papers'] if len(str(p.get('abstract') or p.get('source_excerpt') or ''))>=80}
    closest=result.get('closest_prior_work',[])
    if isinstance(closest,str):closest=[closest]
    supported=isinstance(closest,list) and bool(closest) and all(isinstance(v,str) for v in closest) and set(closest)<=ids
    if result.get('novelty_status') not in {'plausible_delta','overlap_found'} or not supported or not isinstance(result.get('technical_delta'),str) or len(result.get('technical_delta','').strip())<12:
        result.update(novelty_status='unverified',closest_prior_work=[],technical_delta=result.get('technical_delta',''))
        if 'novelty_score' in result:result['novelty_score']=min(2,result['novelty_score'])
    result['novelty_audit']=receipt['receipt']
    result['novelty_limitations']='Existence is separate from novelty. Abstract-only retrieval is not exhaustive prior-art proof.'
    return result
