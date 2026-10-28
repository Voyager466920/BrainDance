"""Project interests, source-backed paper scouting and measured pilot triage."""
from datetime import date,datetime,timedelta,timezone
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess

from tree_store import now

DEFAULTS=dict(style='focused',interests=[],bridge_fields=[],lookback_days=30,max_papers=12,max_pilots=2,pilot_seconds=60,runtime_policy='auto',min_improvement=.05,min_seeds=3)


def validate(value):
    if not isinstance(value,dict) or set(value)-set(DEFAULTS):raise ValueError('지원하지 않는 프로젝트 연구 설정입니다.')
    result={**DEFAULTS,**value}
    if result['style'] not in {'focused','scout'}:raise ValueError('focused 또는 scout 모드를 선택하세요.')
    if result['runtime_policy'] not in {'auto','fixed'}:raise ValueError('실험 시간 배분은 auto 또는 fixed여야 합니다.')
    for key in ['interests','bridge_fields']:
        rows=result[key]
        if not isinstance(rows,list) or len(rows)>12 or any(not isinstance(v,str) or not v.strip() or len(v)>200 for v in rows):raise ValueError('관심 분야·연결 분야는 각각 최대 12개, 항목당 200자입니다.')
        result[key]=list(dict.fromkeys(v.strip() for v in rows))
    for key,low,high in [('lookback_days',1,365),('max_papers',1,40),('max_pilots',1,10),('pilot_seconds',1,86400),('min_seeds',2,20)]:
        if type(result[key]) is not int or not low<=result[key]<=high:raise ValueError('탐색 설정 범위를 확인하세요: '+key)
    threshold=result['min_improvement']
    if isinstance(threshold,bool) or not isinstance(threshold,(int,float)) or not math.isfinite(threshold) or not 0<threshold<=10:raise ValueError('개선 기준은 0보다 크고 10 이하인 비율입니다. 0.05는 5%입니다.')
    if result['style']=='scout' and not result['interests']:raise ValueError('탐색 모드에는 관심 분야가 하나 이상 필요합니다.')
    return result


def root(store,project_id):
    with store._connect() as conn:
        row=conn.execute('SELECT n.id FROM nodes n JOIN node_projects p ON p.node_id=n.id WHERE p.project_id=? AND n.parent_id IS NULL',(project_id,)).fetchone()
    if not row:raise KeyError('프로젝트를 찾을 수 없습니다.')
    return store.get_node(row['id'])


def settings(store,project_id):return validate(root(store,project_id)['metadata'].get('research_preferences',{}))


def runtime_budget(prefs,snapshot,remaining_seconds,remaining_runs,style):
    """Allocate existing project time; model requests cannot expand it."""
    remaining=max(0,int(remaining_seconds));slots=max(1,remaining_runs)
    fixed=[p['pilot_seconds'] for p in (prefs,snapshot) if p.get('runtime_policy')=='fixed']
    if fixed:
        cap=min(remaining,86400,*fixed);policy='fixed';recommended=cap
    else:
        cap=min(86400,remaining//slots);policy='auto'
        recommended=min(cap,max(prefs['pilot_seconds'],900 if style=='scout' else 1800))
    return dict(policy=policy,remaining_project_seconds=remaining,remaining_experiments=slots,max_timeout_seconds=cap,recommended_timeout_seconds=recommended,supervisor_enforced=True)


def save(store,project_id,value):
    prefs=validate({**settings(store,project_id),**value});node=root(store,project_id)
    store.update_node(node['id'],metadata=dict(research_preferences=prefs))
    # Existing jobs learn the changed interests through the same direction stream.
    import steering
    steering.record(store,node['id'],'프로젝트 관심 분야·탐색 설정 변경: '+json.dumps(prefs,ensure_ascii=False),'next')
    return prefs


def initialize(store):
    with store._connect() as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS scout_papers (project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE, paper_id TEXT NOT NULL, paper TEXT NOT NULL, kind TEXT NOT NULL, source_receipt TEXT NOT NULL, first_seen_at TEXT NOT NULL, PRIMARY KEY(project_id,paper_id))')
        conn.execute('CREATE TABLE IF NOT EXISTS scout_searches (project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE, query_key TEXT NOT NULL, receipt TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(project_id,query_key))')


def canonical(paper):
    doi=paper.get('doi')
    if isinstance(doi,str) and doi:identity='doi:'+doi.lower().removeprefix('https://doi.org/').removeprefix('doi:')
    else:
        arxiv=paper.get('arxiv_id') or paper.get('id','')
        arxiv=re.sub(r'^https?://arxiv.org/(abs|pdf)/','',str(arxiv)).removeprefix('arxiv:')
        match=re.fullmatch(r'(\d{4}\.\d{4,5})(v\d+)?',arxiv)
        identity='arxiv:'+match[1] if match else str(paper.get('id') or paper.get('url') or '').rstrip('/')
    if not identity or not paper.get('title'):raise ValueError('조회된 논문의 식별자와 제목이 필요합니다.')
    return identity


def accept(store,project_id,papers,kind,receipt,prefs):
    initialize(store);root(store,project_id)
    if kind not in {'recent','cross-domain'}:raise ValueError('recent 또는 cross-domain 논문을 선택하세요.')
    cutoff=date.today()-timedelta(days=prefs['lookback_days']);new=[];seen=[];excluded=[]
    with store._connect() as conn:
        for paper in papers:
            pid=canonical(paper)
            if kind=='recent':
                try:published=date.fromisoformat(str(paper.get('published') or paper.get('publication_date'))[:10])
                except ValueError:excluded.append(dict(id=pid,reason='publication_date_unknown'));continue
                if published<cutoff or published>date.today():excluded.append(dict(id=pid,reason='outside_date_window'));continue
            old=conn.execute('SELECT 1 FROM scout_papers WHERE project_id=? AND paper_id=?',(project_id,pid)).fetchone()
            if old:seen.append(pid);continue
            normalized={**paper,'canonical_id':pid,'discovery_kind':kind}
            conn.execute('INSERT INTO scout_papers VALUES(?,?,?,?,?,?)',(project_id,pid,json.dumps(normalized,ensure_ascii=False),kind,str(receipt),now()));new.append(normalized)
    return dict(papers=new,already_seen=seen,excluded=excluded,source_receipt=str(receipt))


def paper_view(value):
    result=dict(value)
    result['papers']=[{**{k:p[k] for k in ['id','canonical_id','title','doi','arxiv_id','published','publication_date','url','abs_url','discovery_kind','bridge_domain'] if k in p},'abstract_excerpt':str(p.get('abstract') or '')[:1800],'coverage':'first 1800 abstract characters; full source retained'} for p in value.get('papers',[])]
    return result


def search(job,work,args):
    """Run upstream source clients, retain raw output, then deduplicate per project."""
    import council
    from tree_store import TreeStore
    store=TreeStore(job['db']);prefs=settings(store,job['project_id']);initialize(store)
    source=args.get('source','arxiv');kind=args.get('kind','recent');query=args.get('query','')
    if source not in {'arxiv','openalex'} or kind not in {'recent','cross-domain'} or not isinstance(query,str) or not query.strip() or len(query)>500:raise ValueError('논문 검색어·출처·종류를 확인하세요.')
    limit=args.get('limit',prefs['max_papers'])
    if type(limit) is not int or not 1<=limit<=prefs['max_papers']:raise ValueError('검색 결과 수가 프로젝트 논문 한도를 넘었습니다.')
    domain=args.get('domain') or (prefs['bridge_fields'][0] if prefs['bridge_fields'] else 'auto-selected adjacent field')
    if not isinstance(domain,str) or not domain.strip() or len(domain)>200:raise ValueError('연결 분야 이름을 확인하세요.')
    key=hashlib.sha256(json.dumps(dict(query=query,source=source,kind=kind,limit=limit,day=date.today().isoformat(),days=prefs['lookback_days']),sort_keys=True).encode()).hexdigest()
    with store._connect() as conn:old=conn.execute('SELECT receipt FROM scout_searches WHERE project_id=? AND query_key=?',(job['project_id'],key)).fetchone()
    if old and Path(old['receipt']).is_file():
        cached=json.loads(Path(old['receipt']).read_text());return dict(papers=[],already_seen=[p['canonical_id'] for p in cached['papers']],cached=True,prior_result=paper_view(cached),source_receipt=old['receipt'])
    folder=Path(job['run_dir'])/'scout-searches'/key;folder.mkdir(parents=True,exist_ok=True)
    if source=='arxiv':
        if kind=='recent':
            cutoff=(date.today()-timedelta(days=prefs['lookback_days'])).strftime('%Y%m%d')
            query='('+query+') AND submittedDate:['+cutoff+'0000 TO '+date.today().strftime('%Y%m%d')+'2359]'
        script=Path(job['aris_repo'])/'tools/arxiv_fetch.py';argv=['search',query,'--max',str(limit)]
    else:
        script=Path(job['aris_repo'])/'tools/openalex_fetch.py';argv=['search',query,'--max',str(limit),'--json']
        if kind=='recent':argv+=['--year',str(date.today().year-1)+'-'+str(date.today().year),'--sort','date']
    (folder/'request.json').write_text(json.dumps(dict(source=source,kind=kind,args=argv,bridge_domain=domain if kind=='cross-domain' else None),ensure_ascii=False))
    try:
        result=subprocess.run(council.python_command(script)+argv,cwd=work,capture_output=True,text=True,timeout=120)
    except subprocess.TimeoutExpired as error:
        (folder/'stderr.log').write_text('Source timeout: '+str(error));raise ValueError('논문 출처 조회 시간이 초과됐습니다. 다른 출처를 시도하세요.')
    (folder/'stdout.json').write_text(result.stdout);(folder/'stderr.log').write_text(result.stderr)
    if result.returncode:raise ValueError('공식 논문 조회 도구가 실패했습니다. 다른 출처를 시도하세요. 오류: '+result.stderr[-1500:])
    papers=json.loads(result.stdout)
    if not isinstance(papers,list):raise ValueError('논문 조회 결과 형식이 올바르지 않습니다.')
    if kind=='cross-domain':papers=[{**paper,'bridge_domain':domain} for paper in papers]
    receipt=folder/'accepted.json';value=accept(store,job['project_id'],papers,kind,receipt,prefs)
    receipt.write_text(json.dumps(value,ensure_ascii=False,indent=2))
    with store._connect() as conn:conn.execute('INSERT OR REPLACE INTO scout_searches VALUES(?,?,?,?)',(job['project_id'],key,str(receipt),now()))
    return paper_view(value)


def triage(run,prefs):
    result=run.get('result') or {};metrics=result.get('metrics') or {};analysis=result.get('analysis') or {}
    verdict=dict(run_id=run['id'],promising=False,status='inconclusive',reasons=[])
    if run.get('state')!='succeeded' or analysis.get('status')!='compared':verdict['reasons'].append('완료된 기준선·후보 측정이 없습니다.');return verdict
    a,b=analysis['baseline'],analysis['candidate'];direction=analysis['direction'];sign=1 if direction=='maximize' else -1
    if abs(a)<1e-12:verdict['reasons'].append('기준선이 0이므로 상대 개선율을 판정하지 않습니다.');return verdict
    improvement=sign*(b-a)/abs(a);verdict['relative_improvement']=improvement
    seeds=metrics.get('seeds',[]);valid=[];identities=set();metric=analysis['metric']
    for row in seeds if isinstance(seeds,list) else []:
        if not isinstance(row,dict) or type(row.get('seed')) is not int or row['seed'] in identities:continue
        if not isinstance(row.get('baseline'),dict) or not isinstance(row.get('candidate'),dict):continue
        baseline=row['baseline'].get(metric);candidate=row['candidate'].get(metric)
        if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in [baseline,candidate]):continue
        identities.add(row['seed']);valid.append((baseline,candidate))
    if valid and (not math.isclose(sum(x for x,y in valid)/len(valid),a,rel_tol=1e-7,abs_tol=1e-9) or not math.isclose(sum(y for x,y in valid)/len(valid),b,rel_tol=1e-7,abs_tol=1e-9)):verdict['reasons'].append('전체 지표가 seed별 측정 평균과 일치하지 않습니다.')
    verdict.update(seed_count=len(valid),positive_seeds=sum(sign*(y-x)>0 for x,y in valid),status='measured')
    if len(valid)<prefs['min_seeds']:verdict['reasons'].append('유망성 판정에 필요한 독립 seed 측정이 부족합니다.')
    if improvement<prefs['min_improvement']:verdict['reasons'].append('상대 개선율이 설정 기준에 못 미칩니다.')
    if not valid or sum(sign*(y-x)>0 for x,y in valid)/len(valid)<2/3:verdict['reasons'].append('seed별 개선 방향이 충분히 일관되지 않습니다.')
    verdict['promising']=not verdict['reasons']
    return verdict


CONTRACT='''SCOUTING MODE (the focused full-Council requirement is adapted below): Keep ARIS as the main executor and its original Reviewer. Load the official research-lit Skill as well as the core pipeline/nested Skills. Use mcp__codex__paper_search for actual recent and cross-domain paper retrieval; it calls upstream source tools and retains dates, raw abstracts, IDs and project-scoped duplicate receipts. Use context.research_preferences for the user's interests, bridge_fields, recency window and pilot limits. When bridge_fields is empty, autonomously choose a plausible adjacent field and record its name in paper_search.domain plus the transfer rationale; do not stop to ask the user to choose one. An older cross-domain paper is allowed when explicitly labelled cross-domain; do not call it a new paper.
First cheaply screen the retrieved candidates yourself, rank connections to the user's interests, and write SCOUT_IDEAS.md with source IDs, transferable mechanism, closest work, feasibility, a falsifiable question, controls and a small pilot. Use new candidates rather than re-testing previously seen papers. A cached search may finish an interrupted pilot, but do not repeat completed old pilots. Do not bypass paper_search by inventing an index. Before submitting an experiment call scout_candidates to register the retrieved canonical paper IDs and interest/mechanism/experiment connection.
Do NOT run a full ideas Council for every paper. Its advice is optional before scouting pilots; preserve the original ARIS independent/code Reviewer. Implement and debug small Python pilots through the existing experiment tool only, within the project's selected GPU/local resources and total run/runtime/model limits. context.execution_budget is authoritative: runtime_policy=auto allocates time automatically from remaining project time and experiment slots; pilot_seconds is only a hint in auto mode, NOT a 60-second hard limit. You need not ask the human to adjust per-pilot seconds. Read BRAINDANCE_TIMEOUT_SECONDS/BRAINDANCE_DEADLINE_UNIX if code needs an internal deadline. The supervisor enforces the granted timeout even if internal timing guards differ or are absent. Only explicit fixed policy imposes a per-pilot hard cap. Do not silently launch a full training study. Generate measured baseline/candidate aggregate arithmetic means AND metrics.seeds=[{seed:integer,baseline:{<metric>:value},candidate:{<metric>:value}}] for at least min_seeds distinct seeds; preserve train/test separation and controls.
Call scout_triage on actual completed receipts. The host decides whether the configured relative gain and seed consistency warrant further review; a small positive pilot is not proof of significance or novelty. If a pilot passes that screen, obtain results Council advice (plus the original ARIS Reviewer); report the connection, source links, actual design, data/model/target, baseline/candidate/seed values, gain, limitations and a concrete next step in NARRATIVE_REPORT.md. The host publishes promising results into the SAME project conversation. Negative/failed pilots remain in the journal and a concise search summary without flooding the main stream with a detailed success report. Finish the bounded scout session even when no candidate is promising; do not block merely for a negative scientific result. All absent/failed data stay explicit. Automatic repeated scheduling is not requested: one start performs one bounded search-and-pilot batch; the user can start another batch later.
'''


def candidate(store,project_id,node_id,session_id,args):
    prefs=settings(store,project_id);ids=args.get('paper_ids',[])
    if not isinstance(ids,list) or not 1<=len(ids)<=5 or not all(isinstance(v,str) for v in ids):raise ValueError('연결할 조회 논문 식별자를 1–5개 선택하세요.')
    fields={k:args.get(k,'') for k in ['interest','mechanism','hypothesis','experiment']}
    if fields['interest'] not in prefs['interests'] or any(not isinstance(v,str) or not v.strip() or len(v)>3000 for v in fields.values()):raise ValueError('프로젝트 관심 분야와 구체적인 연결 가설·실험 설계가 필요합니다.')
    initialize(store);papers=[]
    with store._connect() as conn:
        for pid in ids:
            row=conn.execute('SELECT paper FROM scout_papers WHERE project_id=? AND paper_id=?',(project_id,pid)).fetchone()
            if not row:raise ValueError('실제로 조회·기록한 이 프로젝트 논문만 연결할 수 있습니다.')
            papers.append(json.loads(row['paper']))
    key=hashlib.sha256(json.dumps(dict(papers=sorted(ids),interest=fields['interest'],hypothesis=fields['hypothesis']),sort_keys=True).encode()).hexdigest()
    nodes=[n for n in store.export_json()['nodes'] if n['project_id']==project_id and n['metadata'].get('scout_candidate_key')==key]
    if nodes:
        node=nodes[0]
        store.update_node(node['id'],metadata=dict(scout_session=session_id))
        with store._connect() as conn:
            old=conn.execute("SELECT r.id FROM experiment_runs r JOIN experiments e ON r.experiment_id=e.id WHERE e.node_id=? AND r.state='succeeded'",(node['id'],)).fetchone()
        if old:raise ValueError('이미 실험한 연결 가설입니다. 새 논문·새 비교를 선택하세요.')
    else:
        node=store.add_node(node_id,fields['hypothesis'][:180],kind='hypothesis',evidence=papers,metadata=dict(scout_candidate_key=key,scout_session=session_id,**fields))
        store.add_note(node['id'],'idea','논문 × 관심 분야 연결',json.dumps(dict(papers=papers,**fields),ensure_ascii=False,indent=2))
    return dict(node_id=node['id'],paper_ids=ids,**fields)


def finish(server,job,session,rows,report):
    """Publish only receipt-backed promising pilots into the existing project stream."""
    config=job['config'];work=Path(config['native_workspace']);prefs=settings(server.store,job['project_id'])
    searches=list(Path(job['run_dir']).glob('scout-searches/*/accepted.json'))
    previous=work/'scout-source-receipts.json'
    records=json.loads(previous.read_text()) if previous.exists() else []
    recorded=[p for p in records if p.get('session_id')==session['id'] and Path(p.get('source_receipt','')).is_file()]
    if not searches and not recorded:raise ValueError('실제 논문 조회 기록 없이 탐색을 완료할 수 없습니다.')
    if any(r['state'] in {'queued','running'} for r in rows):raise ValueError('실행 중인 작은 실험을 먼저 확인하세요.')
    receipts=[server.experiments.run_info(r['id']) for r in rows];evaluations=[triage(r,prefs) for r in receipts]
    promising=[r for r in evaluations if r['promising']]
    if receipts:
        reviewer_path=work/'reviewer-latest.json'
        if not reviewer_path.is_file():raise ValueError('실험 결과에 대한 기존 Reviewer 기록이 필요합니다.')
        reviewer=json.loads(reviewer_path.read_text())
        if set(reviewer['run_ids'])!={r['id'] for r in rows} or not Path(reviewer['receipt']).is_file():raise ValueError('최신 결과를 기존 Reviewer가 검토해야 합니다.')
    if promising:
        advice=work/'advice-results.json'
        if not advice.is_file():raise ValueError('유망 후보는 결과 Council 검토 후 보고하세요.')
        data=json.loads(advice.read_text())
        if set(data['run_ids'])!={r['id'] for r in rows}:raise ValueError('최신 유망 후보의 Council 의견이 필요합니다.')
        status=Path(data['path'])/'status.json'
        if not status.is_file() or json.loads(status.read_text()).get('status')!='completed':raise ValueError('Council 검토가 완료되지 않았습니다.')
    path=Path(report)
    if path.is_symlink() or not path.resolve().is_relative_to(work):raise ValueError('프로젝트 작업공간의 보고서만 저장할 수 있습니다.')
    text=path.read_text()
    if not text.strip():raise ValueError('탐색 보고가 비어 있습니다.')
    archive=Path(job['run_dir'])/'native-summary.md';archive.write_text(text)
    ideas=work/'SCOUT_IDEAS.md'
    if ideas.is_file() and not ideas.is_symlink():
        content=ideas.read_text();(Path(job['run_dir'])/'scout-ideas.md').write_text(content)
        server.store.add_note(job['node_id'],'idea','탐색 연결 후보와 선별 근거',content[:99000])
    record=dict(job_id=job['id'],auto_session_id=session['id'],run_ids=[r['id'] for r in rows],report=str(archive),report_sha256=hashlib.sha256(text.encode()).hexdigest(),completed_at=now(),research_style='scout',promising_count=len(promising),triage=evaluations,outcome='promising' if promising else 'no_promising_candidate')
    (Path(job['run_dir'])/'scout-triage.json').write_text(json.dumps(evaluations,ensure_ascii=False,indent=2))
    if promising:
        server.store.add_note(job['node_id'],'analysis','탐색 보고 · 유망 후보 '+str(len(promising))+'개',text+'\n\n실제 측정 기반 판정\n'+json.dumps(evaluations,ensure_ascii=False,indent=2))
    else:server.store.add_note(job['node_id'],'memo','탐색 완료 · 유망 후보 없음',text[:99000])
    (work/'native-completion.json').write_text(json.dumps(record,ensure_ascii=False,indent=2))
    return record
