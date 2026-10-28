"""Readable, deterministic views of retained research records. Never starts work."""
from datetime import datetime,timezone
import json
import re
import time
from zoneinfo import ZoneInfo

from terminal import PHASES,safe_text
from prompt_toolkit.utils import get_cwidth


def deadline_text(epoch):
    end=datetime.fromtimestamp(epoch,ZoneInfo('Asia/Seoul')).strftime('%m/%d %H:%M')
    return '종료 '+end+' · 남은 '+duration(max(0,epoch-time.time()))

STATES={'active':'활성','expanded':'확장','held':'보류','discarded':'폐기','queued':'대기','preparing':'준비',
 'running':'진행 중','paused':'일시정지','blocked':'확인 필요','completed':'완료','succeeded':'성공',
 'failed':'실패','cancelled':'취소','interrupted':'중단됨','stopped':'중지','timed_out':'시간 초과'}
LABELS={'ready':'준비 여부','blockers':'필요한 항목','summary':'요약','title':'제목','hypothesis':'가설',
 'novelty':'신규성','feasibility':'실현 가능성','evidence':'논문 근거','reasons':'평가 근거','verdict':'평가',
 'limitations':'한계','dependencies':'필요 조건','expected_experiment':'예상 실험','experiment':'실험 계획',
 'next_experiment':'다음 실험','metric':'평가 지표','metrics':'측정 결과','baseline':'기준선','candidate':'후보',
 'accuracy':'정확도','direction':'평가 방향','timeout_seconds':'최대 실행 시간(초)','interpreter':'Python 환경',
 'cwd':'작업 폴더','args':'실행 인수','control':'대조군','conclusion':'결론','result':'결과',
 'decision':'다음 결정','recommendation':'제안','priority':'우선순위','confidence':'확신도',
 'findings':'관찰','analysis':'분석','improvement':'개선','status':'상태','value':'측정값','delta':'차이',
 'observation':'관찰','description':'설명','code':'실험 코드','quote':'인용','url':'출처',
 'research_question':'연구 질문','method':'방법','risks':'위험 요소','rationale':'근거','notes':'기록',
 'maximize':'높을수록 좋음','minimize':'낮을수록 좋음','max_calls':'총 호출 한도','max_model_calls':'총 호출 한도',
 'calls_used':'사용한 호출','token_budget':'토큰 한도','charged_tokens':'토큰 예상·예약',
 'model_dataset_candidates':'모델·데이터 후보','comparison':'비교 조건','primary_metric':'주요 지표',
 'expected_outcome':'예상 결과','resources':'실행 자원','compute_budget':'자원 예산',
 'evaluation_protocol':'평가 절차','success_criteria':'성공 기준','baseline_methods':'기준선 방법',
 'validation':'검증','ablation':'절제 실험','settings':'설정'}
STEPS=['literature','verification','generation','peer-review','chairman','environment','coding','code-review','experiment_approval','run','analysis']


def label(value):return LABELS.get(value,STATES.get(value,PHASES.get(value,str(value).replace('_',' '))))


def readable(value,depth=0):
    """Keep the full source in storage; present structured values as labelled prose."""
    pad='  '*depth
    if isinstance(value,dict):
        lines=[]
        for key,item in value.items():
            if key in {'session_id','project_id','node_id','request_id','run_id','digest','resource_signature'}:continue
            if key in {'code','source_code'}:
                if item:lines.append(pad+'실험 코드: 계획 탭에서 확인')
                continue
            if item in ('',None,[],{}):continue
            if isinstance(item,(dict,list)):lines.extend([pad+label(key),readable(item,depth+1)])
            else:lines.append(pad+label(key)+': '+readable(item))
        return '\n'.join(lines)
    if isinstance(value,list):
        return '\n'.join(pad+'• '+readable(item,depth+1).lstrip() for item in value)
    if value is True:return '예'
    if value is False:return '아니요'
    if value is None:return '미확인'
    if isinstance(value,(int,float)):return str(value)
    text=safe_text(value).strip()
    try:
        if text[:1] in {'{','['}:
            parsed=json.loads(text)
            if isinstance(parsed,(dict,list)):return readable(parsed,depth)
    except (ValueError,RecursionError):pass
    text=re.sub(r'```(?:json)?\s*([\s\S]*?)```',lambda m:readable(m.group(1),depth),text)
    text=re.sub(r'(?m)^#{1,6}\s+','',text)
    text=text.replace('**','').replace('```','')
    return label(text) if text in LABELS or text in STATES else text


def short(value,length=100):
    value=' '.join(readable(value).split())
    return value if len(value)<=length else value[:length-1]+'…'


def clip_cells(value,width):
    text=' '.join(readable(value).split());result='';used=0
    if get_cwidth(text)<=width:return text
    for char in text:
        size=get_cwidth(char)
        if used+size>max(0,width-1):break
        result+=char;used+=size
    return result+'…' if width>0 else ''


def wrap_cells(text,width):
    """Physical terminal rows, including CJK, so scrolling is independent of wrapping."""
    width=max(2,width);rows=[]
    for line in text.expandtabs(4).split('\n'):
        row='';used=0
        for char in line:
            size=get_cwidth(char)
            if used+size>width:
                rows.append(row);row='';used=0
            row+=char;used+=size
        rows.append(row)
    return '\n'.join(rows)


def report_view(state):
    link=state.get('link');lines=['결과 · Notion','']
    lines.append(('연결 확인됨' if state.get('connected') and link else 'Notion 연결 설정 필요')+(' · 자동 동기화 ON' if link and link['auto_sync'] else ''))
    if link:lines.append('상위 페이지 https://www.notion.so/'+link['parent_id'].replace('-',''))
    jobs=state.get('jobs',[])
    for job in jobs[:3]:
        lines.extend(['',('Notion' if job['kind'] in {'notion','notion-database'} else '로컬 보고서')+' · '+job['message']])
        if job.get('page_url'):lines.append(job['page_url'])
    record=state.get('report')
    if not record:return '\n'.join(lines+['','보고서를 만들면 논문 근거·가설·평가·실험 결과를 함께 정리합니다.'])
    lines.extend(['','시각화 '+str(len(record['charts']))+'개 · '+clock(record['created_at'])])
    for chart in record['charts']:
        lines.extend(['',chart['title']])
        for row in chart['rows']:
            lines.append(row['label']+' · '+row['title'])
            for kind,value in row['values']:lines.append('  '+kind+': '+format(value,'.6g'))
    for title,body in record['sections']:lines.extend(['',title,body])
    return '\n'.join(lines)


def clock(value):
    try:return datetime.fromisoformat(str(value).replace('Z','+00:00')).astimezone().strftime('%m/%d %H:%M')
    except (ValueError,TypeError):return '—'


def age_seconds(value):
    try:return max(0,(datetime.now(timezone.utc)-datetime.fromisoformat(value.replace('Z','+00:00'))).total_seconds())
    except (ValueError,TypeError,AttributeError):return None


def duration(value):
    if not isinstance(value,(int,float)):return '미확인'
    value=max(0,int(value));return f'{value//60}분 {value%60:02d}초' if value>=60 else f'{value}초'


def provider_line(data,compact=False):
    result=[]
    for p in data.get('providers',[]):
        connected=p.get('connection') in {'connected','authenticated'}
        windows=[]
        for w in p.get('windows',[]):
            used=w.get('used_percent');minutes=w.get('minutes')
            window=('주' if compact else '주간') if minutes==10080 else ('5h' if compact else '5시간') if minutes==300 else '한도'
            windows.append(window+' '+(f'{used:g}%' if isinstance(used,(int,float)) else '미확인'))
        result.append(p.get('name','계정')+' '+(('연결' if compact else '연결됨') if connected else '로그인 필요' if p.get('connection')=='signed_out' else '확인 중')+(' · '+', '.join(windows) if windows else ' · 사용량 미확인'))
    return '    '.join(result) or 'GPT · Claude 연결 확인 중…'


def device_label(device):
    if device.get('id')=='cpu':return 'CPU'
    if device.get('kind')=='cuda':
        index=device.get('index');prefix='GPU '+str(index) if type(index) is int else 'GPU 번호 미확인'
    else:prefix='GPU'
    return prefix+' · '+safe_text(device.get('name','장치'))


def connection_error(value):
    text=safe_text(value)
    if 'Connection refused' in text:return 'SSH 포트 연결 거부 · 서버 또는 터널을 확인하세요.'
    if 'timed out' in text or 'Timeout' in text:return 'SSH 응답 시간 초과 · 서버 연결을 확인하세요.'
    if 'Permission denied' in text:return 'SSH 인증 실패 · 사용자와 기존 키 설정을 확인하세요.'
    return readable(text)


def resource_info(compute,project_id):
    assignment=compute.get('assignments',{}).get(project_id)
    if not assignment:return dict(text='실행 환경 미설정 · 설정에서 선택',assignment=None,profile=None,inventory={})
    profile=next((p for p in compute.get('profiles',[]) if p['id']==assignment['profile_id']),None)
    if not profile:return dict(text='실행 환경을 찾을 수 없습니다.',assignment=assignment,profile=None,inventory={})
    inventory=compute.get('inventories',{}).get(profile['id'],{})
    devices={d['id']:d for d in inventory.get('devices',[])}
    selected=[devices.get(identity,dict(id=identity,name=identity if identity=='cpu' else '장치 확인 필요',kind='cuda' if identity.startswith('GPU-') else 'unknown')) for identity in assignment.get('device_ids',[])]
    location='로컬' if profile['kind']=='local' else 'SSH '+profile.get('name',profile.get('host',''))
    if inventory.get('hostname'):location+=' / '+inventory['hostname']
    receipt=('조회 '+clock(inventory['checked_at'])) if inventory.get('connected') else '연결 실패' if inventory.get('connected') is False else '연결 미확인'
    text=location+' · '+', '.join(device_label(d) for d in selected)+' · '+receipt
    return dict(text=safe_text(text),assignment=assignment,profile=profile,inventory=inventory,devices=selected)


def phase_status(state,jobs,job_info=None):
    session=state.get('session') or {};runs=state.get('runs',[])
    active=next((j for j in jobs if j['state'] in {'running','queued'}),None)
    job=active or (jobs[0] if jobs else {})
    phase='run' if runs else job.get('phase','prepare')
    phase={'analyzed':'analysis','registering':'experiment_approval'}.get(phase,phase)
    status=('running' if runs else active.get('state') if active else session.get('status') or job.get('state') or 'idle')
    if phase=='blocked' and job_info:
        previous=[e.get('phase') for e in job_info.get('events',[]) if e.get('phase') in STEPS]
        phase=previous[-1] if previous else phase
    point=STEPS.index(phase) if phase in STEPS else None
    if point is not None:
        bar='['+'━'*point+('●' if status not in {'completed','succeeded'} else '━')+'─'*(len(STEPS)-point-1)+']'
        text=bar+' '+str(point+1)+'/'+str(len(STEPS))+' 단계 위치 · '+PHASES.get(phase,'실험 실행' if phase=='run' else phase)
    else:text='[───────────] '+('대기' if status=='idle' else PHASES.get(phase,'준비'))
    text+=' · '+STATES.get(status,status)
    return safe_text(text)


def conversation(messages):
    chunks=[]
    for m in messages:
        role=m.get('role');title={'user':'나','assistant':'Codex','report':'연구 보고','status':'진행'}.get(role,'기록')
        if role=='status':
            chunks.append('진행 · '+PHASES.get(m.get('phase'),m.get('phase',''))+' · '+short(m.get('content',''),160));continue
        if m.get('title'):title+=' · '+m['title']
        title+='   '+clock(m.get('created_at'))
        ref=m.get('metadata',{}).get('reply_to')
        if ref:title+='\n답글 → '+ref.get('title','문제')
        text='답변 작성 중…' if role=='assistant' and m.get('state') in {'queued','running','preparing'} else readable(m.get('content',''))
        chunks.append(safe_text(title)+'\n'+text)
    return '\n\n'.join(chunks) or '이 프로젝트의 첫 대화를 시작하세요.'


def progress_view(state,jobs,job_info,experiments):
    lines=[];seen=set()
    session=state.get('session')
    if session:
        lines.extend(['자동 연구 · '+STATES.get(session['status'],session['status']),''])
    usage=state.get('usage')
    if usage and usage.get('policy')=='until_deadline':lines.extend([deadline_text(usage['deadline_epoch']),f"모델 호출 {usage['calls']:,}회 · 보고된 토큰 {usage['observed_tokens']:,} · 횟수·토큰 제한 없음",''])
    elif usage:lines.extend([f"모델 호출 {usage['calls']:,} / {usage['max_calls']:,}회",f"토큰 예상·예약 {usage['charged_tokens']:,} / {usage['token_budget']:,}",''])
    budget=experiments.get('budget')
    if budget:lines.extend(['실험 시간 예산','사용 '+duration(budget['spent_seconds'])+' · 예약 '+duration(budget['reserved_seconds'])+' · 남은 '+duration(budget['remaining_seconds']),''])
    if session:
        message=readable(session['message']);lines.extend(['현재 보고',message,'']);seen.add(message)
    for job in jobs[:4]:
        lines.append('연구 작업 · '+STATES.get(job['state'],job['state'])+' · '+clock(job['created_at']))
        message=readable(job.get('message',''))
        if message and message not in seen:lines.append(message);seen.add(message)
        lines.append('')
    if job_info:
        lines.append('최근 진행 기록')
        for event in job_info.get('events',[])[-25:]:
            message=readable(event.get('message',event.get('detail','')))
            if message and message in seen:continue
            lines.append('• '+PHASES.get(event.get('phase'),event.get('phase',''))+' · '+message);seen.add(message)
    return '\n'.join(lines)


def idea_view(node,tree):
    if not node:return '생성된 아이디어와 가설이 여기에 정리됩니다.'
    lines=[node['title'],STATES.get(node['status'],node['status'])+' · 우선순위 '+str(node['priority']),'']
    meta={k:v for k,v in node.get('metadata',{}).items() if k not in {'run','council_run','compute_assignment','project_name','research_goal','title'}}
    if meta:lines.extend([readable(meta),''])
    if node.get('evidence'):lines.extend(['논문 근거',readable(node['evidence']),''])
    for evaluation in tree.get('evaluations',[]):
        if evaluation['node_id']==node['id']:lines.extend(['Council 평가',readable(evaluation['payload']),''])
    for note in tree.get('notes',[]):
        if note['node_id']==node['id'] and note['kind'] not in {'result','analysis'}:lines.extend([note['title'],readable(note['content']),''])
    return '\n'.join(lines)


def plan_view(plan):
    if not plan:return '실험 설계와 실행 가능한 계획이 생성되면 여기에 표시됩니다.'
    spec=plan.get('spec',{})
    if not spec:return plan.get('title','계획')+'\n\n'+readable(plan.get('content',''))
    return '\n'.join([spec['title'],'',readable({k:spec.get(k) for k in ['metric','direction','timeout_seconds','interpreter','cwd','args']}),'',
        '실행 대상: '+spec.get('profile',{}).get('name','미확인'),'장치: '+', '.join(spec.get('device_ids',[])),
        '코드: '+str(len(spec.get('code','').splitlines()))+'줄 · 아래 코드 보기에서 확인','',
        '실행 이력: '+str(len(plan.get('runs',[])))+'회'])


def run_view(run,details=None,latest=None):
    if not run:return '진행 중인 실험과 완료된 측정 결과가 여기에 표시됩니다.'
    actual=details or run
    title=run.get('title','실험');lines=[title,STATES.get(actual['state'],actual['state']),'']
    if latest and latest['id']!=run['id']:
        lines.extend(['이전 실행 기록입니다. 프로젝트의 최신 실행: '+STATES.get(latest['state'],latest['state'])+' · '+clock(latest.get('queued_at')),''])
    if actual.get('started_at'):lines.append('시작 '+clock(actual['started_at']))
    elapsed=age_seconds(actual.get('started_at')) if actual['state']=='running' else actual.get('duration_seconds')
    if elapsed is not None:
        limit=actual.get('timeout_seconds') or 0
        used=min(12,int(elapsed/limit*12)) if limit else 0
        lines.append('시간 사용 ['+'━'*used+'─'*(12-used)+'] '+duration(elapsed)+' / 최대 '+duration(limit))
    if actual.get('error'):lines.extend(['문제',readable(actual['error'])])
    if actual.get('result'):lines.extend(['','실제 실행 결과',readable(actual['result'])])
    for key,title in [('stdout_tail','실행 출력'),('stderr_tail','오류 출력')]:
        if actual.get(key):
            lines.extend(['',title+' · 최근 출력', '\n'.join(readable(line) for line in actual[key].splitlines()[-100:])])
    return '\n'.join(lines)
