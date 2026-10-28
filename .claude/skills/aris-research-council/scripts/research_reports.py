"""Project-scoped, reproducible reports and plots from retained measurements only."""
import ast
import hashlib
import html
import json
import math
from pathlib import Path
import re
import threading

from tree_store import now

PLOT_LOCK=threading.Lock()
TERMINAL={'succeeded','failed','cancelled','timed_out','interrupted','blocked'}
SECRET_KEYS={'token','api_key','authorization','password','secret','identity_file','env','config','run_dir','cwd','device_ids','gpu_uuid','code','source_code','stdout','stderr','stdout_tail','stderr_tail','conversation','transcript','prompt','ssh_config'}


def clean(value):
    if isinstance(value,dict):return {k:clean(v) for k,v in value.items() if k.lower().replace('-','_') not in SECRET_KEYS and not k.lower().endswith(('_password','_secret','_api_key'))}
    if isinstance(value,list):return [clean(v) for v in value]
    if isinstance(value,str):
        value=re.sub(r'\b(?:ntn_|secret_|sk-|xoxb-|xoxp-)[A-Za-z0-9_-]{12,}','[credential removed]',value)
        value=re.sub(r'GPU-[a-fA-F0-9-]{16,}','[device ID removed]',value)
        return re.sub(r'(?i)(bearer\s+)[A-Za-z0-9_.-]{12,}',r'\1[credential removed]',value)
    return value


def text(value):
    if value is None:return ''
    if isinstance(value,str):return value
    if isinstance(value,list):return '\n'.join('• '+text(v) for v in value)
    if isinstance(value,dict):return '\n'.join(str(k)+': '+text(v) for k,v in value.items())
    return str(value)


def narrative(value):
    try:return text(clean(json.loads(value)))
    except (ValueError,TypeError):return clean(value)


def entrypoints(source):
    try:return [n.name+'()' for n in ast.parse(source).body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))][:10]
    except SyntaxError:return []


def project_data(store,project_id):
    tree=store.export_json()
    project=next((p for p in tree['projects'] if p['id']==project_id and not p.get('deleted_at')),None)
    if project is None:raise ValueError('활성 프로젝트를 선택하세요.')
    nodes=[n for n in tree['nodes'] if n['project_id']==project_id];ids={n['id'] for n in nodes}
    plans={p['id']:p for p in tree['experiments'] if p['node_id'] in ids}
    result=dict(schema_version=3,project_id=project_id,title=project['title'],nodes=[],notes=[],evaluations=[],runs=[])
    for n in nodes:
        m=n['metadata'];display=m.get('korean_display',{})
        selected={k:display.get(k,m.get(k)) for k in ['idea','novelty','feasibility','experiment','expected_experiment','research_ratings'] if display.get(k,m.get(k)) is not None}
        result['nodes'].append(dict(id=n['id'],parent_id=n['parent_id'],title=n['title'],kind=n['kind'],status=n['status'],priority=n['priority'],evidence=n['evidence'],details=selected))
    result['notes']=[{**{k:n[k] for k in ['id','kind','title','created_at']},'content':narrative(n['content'])} for n in tree['notes'] if n['node_id'] in ids and n['kind'] in {'idea','literature','analysis','plan','finding','summary','decision','report','reflection','experiment_analysis'}]
    result['goal']=next((n['title'] for n in nodes if not n['parent_id']),project['title'])
    for note in reversed(tree['notes']):
        if note['node_id'] in ids and note['title']=='연구 보고 요약':
            try:result['brief']=validate_brief(json.loads(note['content']))
            except (ValueError,TypeError):continue
            break
    result['evaluations']=[{k:e[k] for k in ['id','node_id','payload','created_at']} for e in tree['evaluations'] if e['node_id'] in ids]
    for run in tree['experiment_runs']:
        if run['project_id']!=project_id or run['state'] not in TERMINAL:continue
        plan=plans.get(run['experiment_id'],{}).get('spec',{})
        result['runs'].append(dict(id=run['id'],title=plan.get('title','실험'),state=run['state'],finished_at=run['finished_at'],duration_seconds=run['duration_seconds'],metric=plan.get('metric',''),direction=plan.get('direction','maximize'),metrics=run['result'].get('metrics'),analysis=run['result'].get('analysis',{}),code_reference=dict(file='experiment-runs/'+run['id']+'/experiment.py',sha256=hashlib.sha256(plan.get('code','').encode()).hexdigest(),entrypoints=entrypoints(plan.get('code',''))) if plan.get('code') else None))
    with store._connect() as conn:
        exists=conn.execute("SELECT 1 FROM sqlite_master WHERE name='automatic_sessions'").fetchone()
        session=conn.execute('SELECT id,status,config,progress FROM automatic_sessions WHERE project_id=? ORDER BY rowid DESC LIMIT 1',(project_id,)).fetchone() if exists else None
    if session:
        cfg=json.loads(session['config']);progress=json.loads(session['progress'])
        result['execution_state']=dict(id=session['id'],status=session['status'],stop_reason=(progress.get('quota_stop') or {}).get('reason'))
        result['quota_guard']=cfg.get('quota_guard')
        result['account_usage']=progress.get('account_usage') or (cfg.get('quota_guard') or {}).get('baseline')
    return clean(result)


def quiescent(store,project_id):
    with store._connect() as conn:
        return not conn.execute("SELECT 1 FROM experiment_runs WHERE project_id=? AND state IN ('queued','running')",(project_id,)).fetchone() and not conn.execute("SELECT 1 FROM research_jobs WHERE project_id=? AND state IN ('queued','running')",(project_id,)).fetchone()


def signature(data):
    # Account allowance changes alone must not produce repeated Notion snapshots.
    stable={k:v for k,v in data.items() if k!='account_usage'}
    return hashlib.sha256(json.dumps(dict(report_format=3,data=stable),ensure_ascii=False,sort_keys=True,allow_nan=False).encode()).hexdigest()


def result_status(data):
    if data.get('study_outcome')=='rejected':return '실패'
    compared=[]
    for r in data.get('runs',[]):
        a=r.get('analysis') or {}
        if r['state']=='succeeded' and a.get('status')=='compared' and number(a.get('baseline')) and number(a.get('candidate')):
            compared.append((a['candidate']-a['baseline'])*(1 if r.get('direction',a.get('direction','maximize'))=='maximize' else -1)>0)
    if compared:return '성공' if any(compared) else '실패'
    if data.get('runs') and all(r['state'] in {'failed','timed_out','blocked'} for r in data['runs']):return '실패'
    return '탐색중'



def number(value):return type(value) in (int,float) and math.isfinite(value)


def measurements(data):
    groups={}
    for index,run in enumerate(data['runs'],1):
        if run['state']!='succeeded':continue
        analysis=run['analysis'];values=[]
        if analysis.get('status')=='compared':values=[('Baseline',analysis.get('baseline')),('Candidate',analysis.get('candidate'))]
        elif analysis.get('status')=='measured':values=[('Measured',analysis.get('value'))]
        if not values or not all(number(v) for _,v in values):continue
        key=(run['metric'],run['direction'])
        groups.setdefault(key,[]).append(dict(run_id=run['id'],label='Run '+str(index),title=run['title'],values=values))
    return groups


def safe_folder(root,project_id,digest):
    if not re.fullmatch(r'[a-f0-9-]{36}',project_id) or not re.fullmatch(r'[a-f0-9]{64}',digest):raise ValueError('보고서 경로가 올바르지 않습니다.')
    root=Path(root)
    if root.is_symlink() or (root/project_id).is_symlink() or (root/project_id/digest).is_symlink():raise ValueError('보고서 경로에 심볼릭 링크를 사용할 수 없습니다.')
    return root/project_id/digest


def build_report(root,data):
    digest=signature(data);folder=safe_folder(root,data['project_id'],digest)
    folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    manifest=folder/'manifest.json'
    if manifest.exists():return json.loads(manifest.read_text())
    sections=editorial_sections(data)
    charts=[];groups=measurements(data)
    if not groups:sections.append(('측정 결과','그래프로 표시할 성공한 실험의 수치가 아직 없습니다. 측정값을 추정하거나 예상 설계를 실험 결과로 표시하지 않습니다.'))
    if groups:
        # Figure/Agg avoids GUI backends in a server thread and is safe in the bundle.
        with PLOT_LOCK:
            from matplotlib.figure import Figure
            from matplotlib.backends.backend_agg import FigureCanvasAgg
            for index,((metric,direction),rows) in enumerate(groups.items(),1):
                for part in range(0,len(rows),15):
                    subset=rows[part:part+15];labels=[];values=[];colors=[]
                    for r in subset:
                        for kind,value in r['values']:
                            labels.append(r['label']+' / '+kind);values.append(value);colors.append('#668c9e' if kind=='Baseline' else '#639e82')
                    fig=Figure(figsize=(9,max(3,1+.36*len(values))),layout='constrained');FigureCanvasAgg(fig);ax=fig.subplots()
                    ax.barh(range(len(values)),values,color=colors);ax.set_yticks(range(len(values)),labels);ax.invert_yaxis()
                    ax.set_title(metric+' — observed results');ax.set_xlabel('Higher is better' if direction=='maximize' else 'Lower is better')
                    ax.axvline(0,color='#a1a7aa',linewidth=.6);ax.grid(axis='x',alpha=.15);ax.set_axisbelow(True)
                    lo=min(0,min(values));hi=max(0,max(values));span=hi-lo or 1;ax.set_xlim(lo-span*.1,hi+span*.28)
                    for y,v in enumerate(values):ax.annotate(format(v,'.5g'),(v,y),xytext=(5 if v>=0 else -5,0),textcoords='offset points',va='center',ha='left' if v>=0 else 'right')
                    name=f'metric-{index:03}-{part//15:03}.png';fig.savefig(folder/name,dpi=150);fig.clear()
                    caption=metric+' · '+('높을수록 좋음' if direction=='maximize' else '낮을수록 좋음')+' · 성공한 실행의 관측값, 통계적 검증은 별도'
                    charts.append(dict(file=name,title=caption,metric=metric,rows=subset))
    markdown='# '+data['title']+'\n\n'
    for title,body in sections:
        markdown+='## '+title+'\n\n'+body+'\n\n'
        if title=='상세 결과':
            for c in charts:markdown+='!['+c['title']+']('+c['file']+')\n\n'
    (folder/'report.md').write_text(markdown,encoding='utf-8')
    (folder/'results.json').write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    record=dict(project_id=data['project_id'],digest=digest,title=data['title'],created_at=now(),charts=charts,sections=sections,files=['report.md','results.json']+[c['file'] for c in charts])
    manifest.write_text(json.dumps(record,ensure_ascii=False,allow_nan=False),encoding='utf-8')
    return record


def report_html(record):
    esc=lambda v:html.escape(str(v),quote=True)
    query='project_id='+record['project_id']+'&digest='+record['digest']+'&file='
    sections=''.join('<section><h2>'+esc(title)+'</h2><pre>'+esc(body)+'</pre></section>' for title,body in record['sections'])
    plots=''.join('<figure><img alt="'+esc(c['title'])+'" src="/api/reports/file?'+query+c['file']+'"><figcaption>'+esc(c['title'])+'</figcaption></figure>' for c in record['charts'])
    return ('<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>'+esc(record['title'])+'</title><style>body{background:#11181d;color:#d7dfe2;font:16px/1.7 system-ui;max-width:1000px;margin:40px auto;padding:24px}pre{white-space:pre-wrap;font:inherit}img{max-width:100%;background:white}figure{margin:30px 0}a{color:#78cbd1}</style><h1>'+esc(record['title'])+'</h1>'+plots+sections+'</html>').encode()

def validate_brief(value):
    if not isinstance(value,dict):raise ValueError('연구 요약은 JSON 객체여야 합니다.')
    result={}
    for key in ['problem','approach','findings']:
        item=value.get(key,'')
        if not isinstance(item,str) or len(item)>8000:raise ValueError('연구 요약의 '+key+' 내용을 확인하세요.')
        result[key]=clean(item.strip())
    for key in ['limitations','next_steps']:
        items=value.get(key,[])
        if not isinstance(items,list) or len(items)>12 or any(not isinstance(v,str) or len(v)>2000 for v in items):raise ValueError('연구 요약의 '+key+' 목록을 확인하세요.')
        result[key]=clean(items)
    return result


def paper_urls(value):
    """The reading report cites URLs only; full source evidence stays local."""
    links=[]
    def visit(item):
        if isinstance(item,dict):
            for key,child in item.items():
                if key in {'url','paper_url','source_url','doi_url'} and isinstance(child,str):visit(child)
                elif isinstance(child,(dict,list)):visit(child)
        elif isinstance(item,list):
            for child in item:visit(child)
        elif isinstance(item,str):
            for url in re.findall(r'https?://[^\s<>\[\]"\)]+',item):
                url=url.rstrip('.,;')
                if url not in links:links.append(url)
    visit(value)
    return links


def reader_prose(value):
    # No bibliography labels, abstracts or serialized evidence in the reading view.
    return re.sub(r'\[([^\]]+)\]\((https?://[^\s)]+)\)',r'\2',str(value)).strip()


def editorial_sections(data):
    brief=data.get('brief') or {};nodes=data['nodes'];runs=data['runs']
    root=next((n for n in nodes if not n['parent_id']),{})
    problem=brief.get('problem') or data.get('goal') or root.get('title') or data['title']
    methods=[]
    for node in nodes:
        if node.get('status')=='discarded':continue
        detail=node.get('details',{})
        idea=detail.get('experiment') or detail.get('expected_experiment') or detail.get('idea')
        if idea:methods.append('- **'+node['title']+'**: '+text(idea))
    approach=brief.get('approach') or '\n'.join(methods[-6:]) or '해결 방법을 아직 검증하지 않았습니다. 현재는 문제와 후보 방법을 탐색 중입니다.'
    code=[];seen=set()
    for run in reversed(runs):
        source=run.get('code_reference') or {}
        if source.get('sha256') in seen or not source.get('file'):continue
        seen.add(source.get('sha256'));code.append('- **'+run['title']+'**\n  - `'+source['file']+'`\n  - 진입점: '+(', '.join('`'+v+'`' for v in source.get('entrypoints',[])) or '모듈 직접 실행'))
    code='\n'.join(code) or '실행 코드가 아직 생성되지 않았습니다.'
    results=[]
    if brief.get('findings'):results.append(reader_prose(brief['findings']))
    if runs:
        rows=['| 실험 | 상태 | 지표 | 기준선 | 제안 방법 | 변화 | 실행 시간 |','| --- | --- | --- | ---: | ---: | ---: | ---: |']
        def fmt(v):return format(v,'.6g') if number(v) else '—'
        for index,run in enumerate(runs,1):
            a=run.get('analysis') or {};valid=run['state']=='succeeded' and a.get('status') in {'compared','measured'}
            baseline=a.get('baseline') if valid else None;candidate=a.get('candidate',a.get('value')) if valid else None
            change=candidate-baseline if number(baseline) and number(candidate) else None
            title=run['title'].replace('|','/').replace('\n',' ');metric=run.get('metric','').replace('|','/')
            status='측정 완료' if valid else run['state']+' · 측정 없음'
            rows.append(f"| {index}. {title} | {status} | {metric} | {fmt(baseline)} | {fmt(candidate)} | {fmt(change)} | {fmt(run.get('duration_seconds'))}초 |")
        results.append('\n'.join(rows))
    else:results.append('완료된 실험이 아직 없습니다. 예상 성능을 실제 결과로 표시하지 않습니다.')
    if measurements(data):results.append('그래프는 성공한 실행의 실제 측정값만 표시합니다. 실행 번호는 위 표와 같습니다. 수치 개선만으로 통계적 유의성이나 신규성이 입증되지는 않습니다.')
    limits=brief.get('limitations') or ['단일 실행과 소규모 실험의 결과를 일반적인 성능 개선으로 단정할 수 없습니다.']
    steps=brief.get('next_steps') or ['다음 연구 단계는 최신 측정 결과와 Reviewer 검토에 따라 갱신합니다.']
    tail='\n'.join('- '+reader_prose(v) for v in limits)+'\n\n**다음 단계**\n\n'+'\n'.join(str(i)+'. '+reader_prose(v) for i,v in enumerate(steps[:3],1))
    urls=paper_urls([n.get('evidence',[]) for n in nodes])
    score_rows=['| 가설 | 유망도 | 잠정 참신도 | 실현 가능성 | 검증 가능성 | 신규성 상태 |','| --- | ---: | ---: | ---: | ---: | --- |']
    for n in nodes:
        r=n.get('details',{}).get('research_ratings')
        if r:score_rows.append('| '+n['title'].replace('|','/')+' | '+' | '.join(str(r.get(k,'—')) for k in ['potential','novelty_provisional','feasibility','falsifiability'])+' | '+str(n.get('details',{}).get('novelty',{}).get('assessment','미검증'))+' |')
    scores=[('가설 평가','점수는 0–100점의 잠정 판단이며 성공 확률이나 실제 성능 측정값이 아닙니다.\n\n'+'\n'.join(score_rows))] if len(score_rows)>2 else []
    from quota_guard import describe
    outcome=result_status(data)
    summary=('개선된 측정값을 관측했습니다. 신규성·통계적 유의성은 별도 검증이 필요합니다.' if outcome=='성공' else data.get('rejection_reason') or '목표 개선을 확인하지 못했거나 실행에 실패했습니다.' if outcome=='실패' else '아직 성공·실패를 판정할 비교 결과가 없습니다.')
    if data.get('execution_state',{}).get('stop_reason'):summary+='\n\n중지 사유: '+data['execution_state']['stop_reason']
    return [('결과','**'+outcome+'**\n\n'+summary),('상세 결과','\n\n'.join(results)),('남은 사용량',describe(data.get('account_usage'),data.get('quota_guard')))]+scores+[('해결하려는 문제',reader_prose(problem)),('해결 방법',reader_prose(approach)),('살펴볼 코드',code),('한계와 다음 단계',tail),('참고 논문','\n'.join(urls) or '아직 인용할 논문 URL이 없습니다.')]
