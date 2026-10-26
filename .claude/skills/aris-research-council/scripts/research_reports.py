"""Project-scoped, reproducible reports and plots from retained measurements only."""
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
        value=re.sub(r'\b(?:ntn_|secret_|sk-)[A-Za-z0-9_-]{12,}','[credential removed]',value)
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


def project_data(store,project_id):
    tree=store.export_json()
    project=next((p for p in tree['projects'] if p['id']==project_id and not p.get('deleted_at')),None)
    if project is None:raise ValueError('활성 프로젝트를 선택하세요.')
    nodes=[n for n in tree['nodes'] if n['project_id']==project_id];ids={n['id'] for n in nodes}
    plans={p['id']:p for p in tree['experiments'] if p['node_id'] in ids}
    result=dict(schema_version=1,project_id=project_id,title=project['title'],nodes=[],notes=[],evaluations=[],runs=[])
    for n in nodes:
        m=n['metadata'];display=m.get('korean_display',{})
        selected={k:display.get(k,m.get(k)) for k in ['idea','novelty','feasibility','experiment','expected_experiment'] if display.get(k,m.get(k)) is not None}
        result['nodes'].append(dict(id=n['id'],parent_id=n['parent_id'],title=n['title'],kind=n['kind'],status=n['status'],priority=n['priority'],evidence=n['evidence'],details=selected))
    result['notes']=[{**{k:n[k] for k in ['id','kind','title','created_at']},'content':narrative(n['content'])} for n in tree['notes'] if n['node_id'] in ids and n['kind'] in {'idea','literature','analysis','plan','finding','summary','decision','report','reflection','experiment_analysis'}]
    result['evaluations']=[{k:e[k] for k in ['id','node_id','payload','created_at']} for e in tree['evaluations'] if e['node_id'] in ids]
    for run in tree['experiment_runs']:
        if run['project_id']!=project_id or run['state'] not in TERMINAL:continue
        plan=plans.get(run['experiment_id'],{}).get('spec',{})
        result['runs'].append(dict(id=run['id'],title=plan.get('title','실험'),state=run['state'],finished_at=run['finished_at'],duration_seconds=run['duration_seconds'],metric=plan.get('metric',''),direction=plan.get('direction','maximize'),metrics=run['result'].get('metrics'),analysis=run['result'].get('analysis',{})))
    return clean(result)


def signature(data):return hashlib.sha256(json.dumps(data,ensure_ascii=False,sort_keys=True,allow_nan=False).encode()).hexdigest()


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
    sections=[('연구 목표',data['title']),('연구 현황',f"가설·질문 {len(data['nodes'])}개 · 종료된 실험 {len(data['runs'])}개\n예상 설계와 실제 측정 결과를 구분합니다. 단일 실행 비교는 통계적 유의성을 뜻하지 않습니다.")]
    for n in data['nodes']:
        sections.append(('가설·질문 · '+n['title'],text(dict(상태=n['status'],우선순위=n['priority'],**n['details']))))
        if n['evidence']:sections.append(('논문 근거',text(n['evidence'])))
    for e in data['evaluations']:sections.append(('Council 평가 · '+next((n['title'] for n in data['nodes'] if n['id']==e['node_id']),'가설'),text(e['payload'])))
    for n in data['notes']:sections.append((n['title'],n['content']))
    for index,run in enumerate(data['runs'],1):
        sections.append((f"Run {index} · {run['title']}",text(dict(상태=run['state'],실행_ID=run['id'],종료=run['finished_at'],실행_초=run['duration_seconds'],지표=run['metric'],방향=run['direction'],측정=run['metrics'],분석=run['analysis']))))
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
                    ax.set_title('Metric '+str(index)+' — observed results');ax.set_xlabel('Higher is better' if direction=='maximize' else 'Lower is better')
                    ax.axvline(0,color='#a1a7aa',linewidth=.6);ax.grid(axis='x',alpha=.15);ax.set_axisbelow(True)
                    lo=min(0,min(values));hi=max(0,max(values));span=hi-lo or 1;ax.set_xlim(lo-span*.1,hi+span*.28)
                    for y,v in enumerate(values):ax.annotate(format(v,'.5g'),(v,y),xytext=(5 if v>=0 else -5,0),textcoords='offset points',va='center',ha='left' if v>=0 else 'right')
                    name=f'metric-{index:03}-{part//15:03}.png';fig.savefig(folder/name,dpi=150);fig.clear()
                    caption=metric+' · '+('높을수록 좋음' if direction=='maximize' else '낮을수록 좋음')+' · 성공한 실행의 관측값, 통계적 검증은 별도'
                    charts.append(dict(file=name,title=caption,metric=metric,rows=subset))
    markdown='# '+data['title']+'\n\n'+'\n\n'.join('## '+title+'\n\n'+body for title,body in sections)
    for c in charts:markdown+='\n\n## '+c['title']+'\n\n!['+c['metric']+']('+c['file']+')\n\n'+'\n'.join(r['label']+': '+r['title']+' · '+r['run_id'] for r in c['rows'])
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
