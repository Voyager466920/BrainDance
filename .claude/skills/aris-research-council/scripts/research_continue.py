"""Explicit continuation of the same project/session with a new execution window."""
import json
import time
from pathlib import Path
from experiments import resource_signature
from research_reports import quiescent
from tree_store import now


def continue_session(controller,item,payload):
    if item['status'] not in {'stopped','completed','paused','blocked'}:raise ValueError('먼저 실행 중인 연구를 중지하거나 일시정지하세요.')
    if payload.get('session_id')!=item['id']:raise ValueError('연구 세션이 바뀌었습니다. 이어가기 설정을 다시 여세요.')
    if not quiescent(controller.store,item['project_id']):raise ValueError('기존 작업의 중지 처리가 끝난 뒤 이어가세요.')
    profile,assignment=controller.experiments._resources(controller.root(item['project_id']))
    if resource_signature(profile,assignment)!=item['config']['resource_signature']:raise ValueError('장치 설정이 바뀌었습니다. 기존 장치로 복원한 뒤 이어가세요.')
    clock=controller.deadline_spec(payload,0)
    old_config=dict(item['config']);old_progress=dict(item['progress'])
    amount=payload.get('quota_drop_percent',(old_config.get('quota_guard') or {}).get('drop_percent'))
    guard=None
    if amount is not None:
        from quota_guard import capture
        if controller.quota_status is None:raise ValueError('계정 사용량 조회를 확인하세요.')
        try:guard=capture(controller.quota_status(force=True),amount)
        except ValueError as error:
            if payload.get('wait_for_quota') is not True:raise
            pending={k:v for k,v in payload.items() if k!='wait_for_quota'}
            pending.update(next_check=time.time()+60)
            progress={**item['progress'],'pending_continuation':pending}
            with controller.store._connect() as c:
                c.execute('UPDATE automatic_sessions SET status=?,progress=?,message=?,updated_at=? WHERE id=?',('paused',json.dumps(progress),'사용량 기준 확인 대기 · '+str(error),now(),item['id']))
            return controller.state(item['project_id'])
    config={**old_config,**clock,'execution_policy':'until_deadline','max_cycles':None,'pipeline':'aris-native','continuation_count':old_config.get('continuation_count',0)+1}
    if 'research_scope' in payload:config['research_scope']=payload['research_scope']
    if config.get('research_scope')=='ideation':config['orchestration']='hypothesis-tasks'
    config.setdefault('original_started_epoch',old_config.get('started_epoch',clock['started_epoch']))
    if not config.get('native_workspace'):
        from project_session import identity
        config['native_workspace']=str(Path(identity(controller.store,item['project_id'])['path'])/'native')
    if guard:config['quota_guard']=guard
    else:config.pop('quota_guard',None)
    progress={k:v for k,v in old_progress.items() if k not in {'quota_stop','account_usage','recovery_after','recovery_error','pending_continuation'}}
    if guard:progress['account_usage']=guard['baseline']
    progress.update(phase='prepare',job_id=None,run_id=None,recovery_after=0)
    from research_tasks import listing
    rows=[r for r in listing(controller.store,item['id']) if r['round']==progress.get('native_cycle',0)]
    updates=[]
    for task in rows:
        if task['state'] in {'completed','rejected'}:continue
        if task['state']=='stopped' and task['message']=='사용자가 이 가설 작업을 중지했습니다.':continue
        if controller.store.get_node(task['node_id'])['status'] not in {'active','expanded'}:continue
        job=controller.research.get(task['job_id']) if task.get('job_id') else None
        # A completion received just before project cancellation remains completed.
        if job and job['state']=='completed' and job['phase']=='native-completed':
            receipt=Path(job['run_dir'])/'native-completion.json'
            done=json.loads(receipt.read_text()) if receipt.is_file() else {}
            if done.get('job_id')==job['id']:
                updates.append((task['id'],'rejected' if done.get('outcome')=='rejected' else 'completed',job['id'],'이전 작업의 완료 결과 유지'))
                continue
        updates.append((task['id'],'queued',None,'기존 가설 작업공간과 기록에서 이어가기'))
    if rows and config.get('orchestration')=='hypothesis-tasks':progress['phase']='tasks'
    from session_budget import update
    update(config['session_budget'],'continue',deadline_epoch=clock['deadline_epoch'],started_epoch=clock['started_epoch'],previous_config=old_config,previous_progress=old_progress,quota_guard=guard)
    with controller.store._connect() as c:
        for task_id,state,job_id,message in updates:
            c.execute('UPDATE research_tasks SET state=?,job_id=?,retry_at=0,message=?,updated_at=? WHERE id=?',(state,job_id,message,now(),task_id))
        c.execute("UPDATE automatic_sessions SET status='running',config=?,progress=?,message=?,updated_at=? WHERE id=?",(json.dumps(config),json.dumps(progress),'기존 연구·대화·실험 기록을 유지하고 새 시간·사용량 기준으로 이어갑니다.',now(),item['id']))
        controller.store._event(c,item['node_id'],'research_continued',dict(session_id=item['id'],continuation_count=config['continuation_count'],deadline_epoch=config['deadline_epoch'],quota_drop_percent=amount,usage_preserved=True))
    controller.quota_next.pop(item['id'],None)
    controller.store.add_note(item['node_id'],'analysis','기존 연구 이어가기',f"동일 세션에서 {clock['duration_seconds']/3600:g}시간 동안 이어갑니다. 사용량 감소 기준: {str(amount)+'%p' if amount is not None else '사용 안 함'}. 기존 대화·연구 작업·결과·누적 사용량을 보존했습니다.")
    return controller.state(item['project_id'])
