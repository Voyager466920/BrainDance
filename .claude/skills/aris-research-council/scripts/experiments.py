"""Approved, bounded experiment queue with exact-code receipts and local/SSH workers."""
import base64
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import re
import shlex
import signal
import subprocess
import sys
import threading
import time
import uuid

from compute import fingerprint, ssh_base, timestamp

TERMINAL={'succeeded','failed','cancelled','timed_out','interrupted','blocked'}
SKILL=Path(__file__).resolve().parent.parent


def encode(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,allow_nan=False)
def digest(value):return hashlib.sha256(encode(value).encode()).hexdigest()


def resource_signature(profile,assignment):
    return digest({'profile':fingerprint(profile),'device_ids':sorted(assignment['device_ids']),
                   'max_parallel_runs':assignment['max_parallel_runs'],
                   'time_budget_minutes':assignment['time_budget_minutes']})


def worker_source():
    path=Path(sys._MEIPASS)/'worker/experiment_worker.py' if getattr(sys,'frozen',False) else Path(__file__).with_name('experiment_worker.py')
    return path.read_text(encoding='utf-8')


def summarize(metrics,metric,direction):
    result={'metric':metric,'direction':direction,'note':'Observed values from one run; no statistical significance is implied.'}
    if not isinstance(metrics,dict):return {**result,'status':'no_metrics'}
    def number(value):return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)
    baseline=metrics.get('baseline',{});candidate=metrics.get('candidate',{})
    a=baseline.get(metric) if isinstance(baseline,dict) else None
    b=candidate.get(metric) if isinstance(candidate,dict) else None
    if number(a) and number(b):
        delta=b-a;improvement=delta if direction=='maximize' else -delta
        result.update(status='compared',baseline=a,candidate=b,delta=delta,
                      observation='candidate_higher_ranked' if improvement>0 else 'baseline_higher_ranked' if improvement<0 else 'equal')
    elif number(metrics.get(metric)):result.update(status='measured',value=metrics[metric])
    else:result['status']='primary_metric_missing'
    return result


class ExperimentEngine:
    def __init__(self,store,compute,compute_state,autostart=True):
        self.store,self.compute,self.compute_state=store,compute,compute_state
        self.on_finished=None
        self.root=Path(store.db_path).parent/'experiment-runs';self.root.mkdir(exist_ok=True,mode=0o700)
        self.lock=threading.RLock();self.stop_event=threading.Event();self.jobs={};self.last_error=None;self._closed=False
        self._lock_file=(self.root/'.executor.lock').open('a+')
        import fcntl
        try:fcntl.flock(self._lock_file,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            self._lock_file.close()
            raise RuntimeError('Another experiment executor already owns this workspace.')
        with self.store._connect() as conn:
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS experiments (
                    id TEXT PRIMARY KEY,node_id TEXT NOT NULL REFERENCES nodes(id),
                    spec TEXT NOT NULL,digest TEXT NOT NULL,created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS experiment_approvals (
                    id TEXT PRIMARY KEY,experiment_id TEXT NOT NULL REFERENCES experiments(id),
                    digest TEXT NOT NULL,created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS experiment_runs (
                    id TEXT PRIMARY KEY,experiment_id TEXT NOT NULL REFERENCES experiments(id),
                    approval_id TEXT NOT NULL UNIQUE REFERENCES experiment_approvals(id),
                    project_id TEXT NOT NULL,epoch TEXT NOT NULL,state TEXT NOT NULL,
                    timeout_seconds INTEGER NOT NULL,queued_at TEXT NOT NULL,
                    started_at TEXT,finished_at TEXT,exit_code INTEGER,duration_seconds REAL,
                    run_dir TEXT NOT NULL,result TEXT NOT NULL,error TEXT
                );
            ''')
            interrupted=[dict(r) for r in conn.execute("SELECT * FROM experiment_runs WHERE state='running'")]
        for run in interrupted:
            self._finish(run['id'],{'state':'interrupted','exit_code':None,'duration_seconds':run['timeout_seconds'],
                                   'warnings':['Previous supervisor stopped without a completion receipt. A rerun requires new approval.']},'Supervisor restarted')
        self.thread=threading.Thread(target=self._loop,name='braindance-experiments',daemon=True)
        if autostart:self.thread.start()

    def _resources(self,node):
        state=self.compute_state();assignment=state['assignments'].get(node['project_id'])
        if not assignment or not assignment.get('device_ids'):raise ValueError('프로젝트의 실행 환경과 장치를 먼저 설정하세요.')
        profile=next((p for p in state['profiles'] if p['id']==assignment['profile_id']),None)
        if not profile:raise ValueError('실행 환경이 없습니다.')
        return profile,assignment

    def create(self,payload,provenance=None):
        allowed={'node_id','title','code','interpreter','cwd','args','timeout_seconds','metric','direction'}
        if set(payload)-allowed:raise ValueError('지원하지 않는 실험 설정입니다.')
        node=self.store.get_node(payload.get('node_id'))
        title=payload.get('title','');code=payload.get('code','')
        if not isinstance(title,str) or not title.strip() or len(title)>200:raise ValueError('실험 제목은 1–200자로 입력하세요.')
        if not isinstance(code,str) or not code.strip() or len(code.encode())>180000:raise ValueError('Python 코드는 최대 180 KB입니다.')
        try:compile(code,'experiment.py','exec')
        except SyntaxError as error:raise ValueError('Python 문법 오류: '+str(error))
        interpreter=payload.get('interpreter','builtin');cwd=payload.get('cwd','');args=payload.get('args',[])
        if not isinstance(interpreter,str) or len(interpreter)>1024 or not interpreter or interpreter.startswith('-') or '\x00' in interpreter or '\n' in interpreter:
            raise ValueError('Python 실행 파일 이름 또는 경로를 입력하세요.')
        if not isinstance(cwd,str) or len(cwd)>2048 or '\x00' in cwd or '\n' in cwd:raise ValueError('작업 폴더 경로가 올바르지 않습니다.')
        if not isinstance(args,list) or len(args)>64 or not all(isinstance(a,str) and len(a)<=2000 and '\x00' not in a for a in args):raise ValueError('인수는 문자열 JSON 배열이어야 합니다.')
        timeout=payload.get('timeout_seconds',60);metric=payload.get('metric','accuracy');direction=payload.get('direction','maximize')
        profile,assignment=self._resources(node)
        if type(timeout) is not int or not 1<=timeout<=assignment['time_budget_minutes']*60:raise ValueError('실험 시간은 프로젝트 시간 예산 안에서 지정하세요.')
        if not isinstance(metric,str) or not metric.strip() or len(metric)>100 or direction not in {'maximize','minimize'}:raise ValueError('평가 지표와 방향을 확인하세요.')
        spec=dict(node_id=node['id'],project_id=node['project_id'],title=title.strip(),code=code,
                  interpreter=interpreter,cwd=cwd,args=args,timeout_seconds=timeout,metric=metric.strip(),direction=direction,
                  profile=profile,device_ids=assignment['device_ids'],resource_signature=resource_signature(profile,assignment))
        if provenance is not None:spec['generation']=provenance
        record=dict(id=str(uuid.uuid4()),node_id=node['id'],spec=spec,digest=digest(spec),created_at=timestamp())
        with self.lock,self.store._connect() as conn:
            self.store._ensure_active(conn,node['id'])
            conn.execute('INSERT INTO experiments VALUES(?,?,?,?,?)',(record['id'],node['id'],encode(spec),record['digest'],record['created_at']))
            self.store._event(conn,node['id'],'experiment_created',{'experiment_id':record['id'],'digest':record['digest']})
        self.store.add_note(node['id'],'experiment','실행 계획: '+title.strip(),
                            '실험 ID: '+record['id']+'\n코드 SHA-256: '+hashlib.sha256(code.encode()).hexdigest()+
                            '\n장치: '+', '.join(spec['device_ids'])+'\n최대 시간: '+str(timeout)+'초\n아직 실행하지 않은 계획입니다.')
        return record

    def experiment(self,experiment_id):
        with self.store._connect() as conn:row=conn.execute('SELECT * FROM experiments WHERE id=?',(experiment_id,)).fetchone()
        if row is None:raise KeyError('Unknown experiment')
        result=dict(row);result['spec']=json.loads(result['spec']);self.store.get_node(result['node_id'])
        return result

    def _current(self,experiment):
        node=self.store.get_node(experiment['node_id'])
        if node['status'] not in {'active','expanded'}:raise ValueError('실행할 노드를 먼저 활성화하세요.')
        profile,assignment=self._resources(node)
        if resource_signature(profile,assignment)!=experiment['spec']['resource_signature']:
            raise ValueError('실행 환경 또는 예산이 변경되었습니다. 계획을 복제하고 다시 승인하세요.')
        return node,profile,assignment

    def approve(self,experiment_id,expected_digest,consent):
        if consent is not True:raise ValueError('코드·장치·시간 예산에 대한 명시적 승인이 필요합니다.')
        with self.lock:
            experiment=self.experiment(experiment_id);self._current(experiment)
            if expected_digest!=experiment['digest']:raise ValueError('계획이 변경되었습니다. 최신 코드를 다시 확인하세요.')
            with self.store._connect() as conn:
                if conn.execute("SELECT id FROM experiment_runs WHERE experiment_id=? AND state IN ('queued','running')",(experiment_id,)).fetchone():
                    raise ValueError('이 실험은 이미 대기 또는 실행 중입니다.')
                pending=conn.execute('SELECT a.* FROM experiment_approvals a LEFT JOIN experiment_runs r ON r.approval_id=a.id WHERE a.experiment_id=? AND r.id IS NULL ORDER BY a.created_at DESC LIMIT 1',(experiment_id,)).fetchone()
                if pending:return dict(pending)
            approval=dict(id=str(uuid.uuid4()),experiment_id=experiment_id,digest=expected_digest,created_at=timestamp())
            with self.store._connect() as conn:
                conn.execute('INSERT INTO experiment_approvals VALUES(?,?,?,?)',tuple(approval.values()))
                self.store._event(conn,experiment['node_id'],'experiment_approved',approval)
            return approval

    def _budget(self,project_id,epoch,limit,conn):
        spent=reserved=0.0
        for run in conn.execute('SELECT * FROM experiment_runs WHERE project_id=? AND epoch=?',(project_id,epoch)):
            if run['state'] in {'queued','running'}:reserved+=run['timeout_seconds']
            elif run['state']=='interrupted':spent+=run['timeout_seconds']
            else:spent+=max(0,run['duration_seconds'] or 0)
        return dict(limit_seconds=limit,spent_seconds=spent,reserved_seconds=reserved,remaining_seconds=max(0,limit-spent-reserved))

    def enqueue(self,experiment_id,approval_id):
        with self.lock,self.store._connect() as conn:
            if self._closed:raise ValueError('실행기가 종료 중입니다.')
            conn.execute('BEGIN IMMEDIATE')
            old=conn.execute('SELECT * FROM experiment_runs WHERE approval_id=?',(approval_id,)).fetchone()
            if old:
                if old['experiment_id']!=experiment_id:raise ValueError('Approval does not match experiment')
                return self._run_dict(old)
            approval=conn.execute('SELECT * FROM experiment_approvals WHERE id=? AND experiment_id=?',(approval_id,experiment_id)).fetchone()
            if approval is None:raise ValueError('먼저 이 실험의 코드와 예산을 승인하세요.')
            experiment=self.experiment(experiment_id);node,_,assignment=self._current(experiment)
            if approval['digest']!=experiment['digest']:raise ValueError('Approval digest mismatch')
            epoch=assignment['updated_at'];timeout=experiment['spec']['timeout_seconds']
            budget=self._budget(node['project_id'],epoch,assignment['time_budget_minutes']*60,conn)
            if timeout>budget['remaining_seconds']+.001:raise ValueError('프로젝트의 남은 시간 예산이 부족합니다. 예약된 실험과 실제 사용 시간을 확인하세요.')
            run_id=str(uuid.uuid4());run_dir=self.root/run_id;run_dir.mkdir(mode=0o700)
            record=dict(id=run_id,experiment_id=experiment_id,approval_id=approval_id,project_id=node['project_id'],epoch=epoch,
                        state='queued',timeout_seconds=timeout,queued_at=timestamp(),started_at=None,finished_at=None,
                        exit_code=None,duration_seconds=None,run_dir=str(run_dir),result={},error=None)
            (run_dir/'spec.json').write_text(encode(experiment),encoding='utf-8')
            conn.execute('INSERT INTO experiment_runs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',tuple(encode(v) if k=='result' else v for k,v in record.items()))
            self.store._event(conn,node['id'],'experiment_queued',{'run_id':run_id,'approval_id':approval_id})
            return record

    @staticmethod
    def _run_dict(row):
        result=dict(row);result['result']=json.loads(result['result']) if isinstance(result['result'],str) else result['result'];return result

    def list(self,node_id):
        node=self.store.get_node(node_id)
        with self.store._connect() as conn:
            if node['kind']=='problem':
                rows=conn.execute('SELECT e.* FROM experiments e JOIN node_projects p ON p.node_id=e.node_id WHERE p.project_id=? ORDER BY e.created_at DESC',(node['project_id'],)).fetchall()
            else:rows=conn.execute('SELECT * FROM experiments WHERE node_id=? ORDER BY created_at DESC',(node_id,)).fetchall()
            experiments=[]
            for row in rows:
                item=dict(row);item['spec']=json.loads(item['spec'])
                approval=conn.execute('SELECT a.id FROM experiment_approvals a LEFT JOIN experiment_runs r ON r.approval_id=a.id WHERE a.experiment_id=? AND r.id IS NULL ORDER BY a.created_at DESC LIMIT 1',(item['id'],)).fetchone()
                item['pending_approval_id']=approval['id'] if approval else None
                item['runs']=[self._run_dict(r) for r in conn.execute('SELECT * FROM experiment_runs WHERE experiment_id=? ORDER BY queued_at DESC',(item['id'],))]
                if conn.execute("SELECT 1 FROM sqlite_master WHERE name='research_analysis_queue'").fetchone():
                    for run in item['runs']:
                        analysis=conn.execute('''SELECT q.state,j.state AS job_state FROM research_analysis_queue q
                            LEFT JOIN research_jobs j ON j.id=q.job_id WHERE q.run_id=?''',(run['id'],)).fetchone()
                        if analysis:run['llm_analysis_state']=analysis['job_state'] or analysis['state']
                experiments.append(item)
            try:
                profile,assignment=self._resources(node);budget=self._budget(node['project_id'],assignment['updated_at'],assignment['time_budget_minutes']*60,conn)
                policy={**assignment,'profile_name':profile['name']}
            except ValueError:budget=None;policy=None
        return dict(experiments=experiments,budget=budget,policy=policy,executor_error=self.last_error)

    def run_info(self,run_id):
        with self.store._connect() as conn:row=conn.execute('SELECT * FROM experiment_runs WHERE id=?',(run_id,)).fetchone()
        if row is None:raise KeyError('Unknown run')
        run=self._run_dict(row);self.experiment(run['experiment_id'])
        for name in ('stdout','stderr'):
            path=Path(run['run_dir'])/(name+'.log')
            if path.exists():
                with path.open('rb') as stream:stream.seek(max(0,path.stat().st_size-32768));run[name+'_tail']=stream.read().decode('utf-8','replace')
            else:run[name+'_tail']=''
        return run

    def file(self,run_id,name):
        run=self.run_info(run_id);root=Path(run['run_dir']).resolve();path=root/name
        allowed={'stdout.log','stderr.log','receipt.json','experiment.py','spec.json','metrics.json'}|{a['path'] for a in run['result'].get('artifacts',[]) if a.get('transferred')}
        if name not in allowed or path.is_symlink() or not path.resolve().is_relative_to(root) or not path.is_file():raise KeyError('Unknown artifact')
        return path

    def cancel(self,run_id):
        with self.lock:
            run=self.run_info(run_id)
            if run['state']=='queued':self._finish(run_id,{'state':'cancelled','duration_seconds':0,'exit_code':None},'Cancelled before dispatch')
            elif run['state']=='running' and run_id in self.jobs:self.jobs[run_id]['cancel'].set()
            return self.run_info(run_id)

    def _finish(self,run_id,result,error=None):
        with self.lock,self.store._connect() as conn:
            row=conn.execute('SELECT * FROM experiment_runs WHERE id=?',(run_id,)).fetchone()
            if row is None or row['state'] in TERMINAL:return
            experiment=conn.execute('SELECT * FROM experiments WHERE id=?',(row['experiment_id'],)).fetchone()
            spec=json.loads(experiment['spec']);result=dict(result)
            result['analysis']=summarize(result.get('metrics'),spec['metric'],spec['direction'])
            finished=timestamp();state=result.get('state','interrupted')
            if state not in TERMINAL:state='interrupted'
            conn.execute('UPDATE experiment_runs SET state=?,finished_at=?,exit_code=?,duration_seconds=?,result=?,error=? WHERE id=?',
                         (state,finished,result.get('exit_code'),result.get('duration_seconds',0),encode(result),error,run_id))
            receipt=dict(run_id=run_id,experiment_id=row['experiment_id'],digest=experiment['digest'],state=state,
                         finished_at=finished,result=result,error=error)
            Path(row['run_dir']).mkdir(exist_ok=True)
            (Path(row['run_dir'])/'receipt.json').write_text(encode(receipt),encoding='utf-8')
            content='실행 ID: '+run_id+'\n상태: '+state+'\n종료 코드: '+str(result.get('exit_code'))+'\n'+json.dumps(result,ensure_ascii=False,indent=2)
            conn.execute('INSERT OR IGNORE INTO notes VALUES(?,?,?,?,?,?)',('run:'+run_id,experiment['node_id'],'result','실험 결과: '+spec['title'],content,finished))
            self.store._event(conn,experiment['node_id'],'experiment_finished',{'run_id':run_id,'state':state})
        self.store.export_json(Path(self.store.db_path).with_suffix('.json'))
        if spec.get('generation') and state in {'succeeded','failed','timed_out'} and self.on_finished:
            try:self.on_finished(run_id)
            except Exception as caught:
                with (self.root/'executor.log').open('a') as stream:stream.write(timestamp()+' analysis queue failed: '+str(caught)+'\n')

    def _keys(self,spec):
        host=spec['profile'].get('host','local')
        return {('cuda',device) if device.startswith(('GPU-','MIG-')) else (host,device) for device in spec['device_ids'] if device!='cpu'}

    def _schedule(self):
        with self.lock:
            with self.store._connect() as conn:
                approvals=[dict(r) for r in conn.execute('SELECT a.* FROM experiment_approvals a LEFT JOIN experiment_runs r ON r.approval_id=a.id WHERE r.id IS NULL ORDER BY a.created_at')]
            for approval in approvals:
                try:
                    experiment=self.experiment(approval['experiment_id']);_,_,assignment=self._current(experiment)
                    if assignment.get('auto_run'):self.enqueue(experiment['id'],approval['id'])
                except (ValueError,KeyError):continue
            with self.store._connect() as conn:queued=[self._run_dict(r) for r in conn.execute("SELECT * FROM experiment_runs WHERE state='queued' ORDER BY queued_at")]
            for run in queued:
                if len(self.jobs)>=4:break
                try:
                    experiment=self.experiment(run['experiment_id']);_,_,assignment=self._current(experiment)
                    if run['epoch']!=assignment['updated_at']:raise ValueError('예산 설정이 변경되었습니다. 다시 승인하세요.')
                except (ValueError,KeyError) as error:
                    self._finish(run['id'],{'state':'blocked','duration_seconds':0,'exit_code':None},str(error));continue
                if sum(job['project_id']==run['project_id'] for job in self.jobs.values())>=assignment['max_parallel_runs']:continue
                keys=self._keys(experiment['spec'])
                if any(keys & job['keys'] for job in self.jobs.values()):continue
                with self.store._connect() as conn:
                    changed=conn.execute("UPDATE experiment_runs SET state='running',started_at=? WHERE id=? AND state='queued'",(timestamp(),run['id'])).rowcount
                if not changed:continue
                job=dict(project_id=run['project_id'],keys=keys,cancel=threading.Event(),thread=None,process=None)
                self.jobs[run['id']]=job
                thread=threading.Thread(target=self._execute,args=(run,experiment,job),daemon=True,name='experiment-'+run['id'][:8])
                job['thread']=thread;thread.start()

    def _loop(self):
        while not self.stop_event.is_set():
            try:self._schedule();self.last_error=None
            except Exception as error:
                self.last_error=str(error)
                with (self.root/'executor.log').open('a') as stream:stream.write(timestamp()+' '+repr(error)+'\n')
            self.stop_event.wait(.2)

    def _transport(self,profile):
        if profile['kind']=='ssh':return ssh_base(profile)+['python3 -u -c '+shlex.quote(worker_source())]
        if getattr(sys,'frozen',False):return [sys.executable,'--experiment-worker']
        return [sys.executable,'-u',str(Path(__file__).with_name('experiment_worker.py'))]

    def _execute(self,run,experiment,job):
        root=Path(run['run_dir']);spec=experiment['spec'];process=None;reader=None;start=time.monotonic();finished=None;error=None
        try:
            # Recheck identity and devices before any GPU process is dispatched.
            node=self.store.get_node(experiment['node_id']);self._current(experiment)
            if spec['device_ids']!=['cpu'] or spec['profile']['kind']=='ssh':
                inventory=self.compute.probe(spec['profile']['id'])
                if not inventory.get('connected') or not set(spec['device_ids'])<={d['id'] for d in inventory['devices']}:
                    raise ValueError('선택한 실행 환경 또는 GPU를 확인할 수 없습니다.')
            self._current(experiment)
            if job['cancel'].is_set():raise InterruptedError('Cancelled before process creation')
            payload=dict(run_id=run['id'],digest=experiment['digest'],run_dir=str(root),remote=spec['profile']['kind']=='ssh',
                         code=spec['code'],interpreter=spec['interpreter'],cwd=spec['cwd'],args=spec['args'],
                         timeout_seconds=run['timeout_seconds'],device_ids=spec['device_ids'])
            (root/'experiment.py').write_text(spec['code'],encoding='utf-8')
            (root/'dispatch.json').write_text(encode({k:v for k,v in payload.items() if k!='code'}),encoding='utf-8')
            with (root/'worker.log').open('wb') as worker_log, (root/'stdout.log').open('wb') as out, (root/'stderr.log').open('wb') as err:
                process=subprocess.Popen(self._transport(spec['profile']),stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                                         stderr=worker_log,text=False,start_new_session=True)
                job['process']=process;process.stdin.write((encode(payload)+'\n').encode());process.stdin.flush()
                inbox=queue.Queue()
                def read():
                    try:
                        while True:
                            line=process.stdout.readline(4*1024*1024)
                            if not line:break
                            inbox.put(line)
                    finally:inbox.put(None)
                reader=threading.Thread(target=read,daemon=True);reader.start();cancel_sent=False;cancel_at=None
                while True:
                    elapsed=time.monotonic()-start
                    try:
                        node=self.store.get_node(experiment['node_id'])
                        if node['status'] not in {'active','expanded'}:job['cancel'].set()
                    except (ValueError,KeyError):job['cancel'].set()
                    if (job['cancel'].is_set() or self.stop_event.is_set()) and not cancel_sent:
                        try:process.stdin.write(b'{"action":"cancel"}\n');process.stdin.flush()
                        except (OSError,BrokenPipeError):pass
                        cancel_sent=True;cancel_at=time.monotonic()
                    if elapsed>run['timeout_seconds']+25 or (cancel_at and time.monotonic()-cancel_at>8):
                        raise TimeoutError('Supervisor lost its completion receipt; target may still be stopping.')
                    try:line=inbox.get(timeout=.2)
                    except queue.Empty:continue
                    if line is None:break
                    event=json.loads(line)
                    if event.get('run_id') not in (None,run['id']):raise ValueError('Worker run identity mismatch')
                    kind=event.get('event')
                    if kind=='started' and (event.get('digest')!=experiment['digest'] or event.get('code_sha256')!=hashlib.sha256(spec['code'].encode()).hexdigest()):raise ValueError('Worker code digest mismatch')
                    if kind=='output':
                        stream={'stdout':out,'stderr':err}.get(event.get('stream'))
                        if stream is None:raise ValueError('Unknown output stream')
                        stream.write(base64.b64decode(event['data'],validate=True));stream.flush()
                    elif kind=='artifact':
                        relative=event['path'];path=root/relative
                        if not (relative=='metrics.json' or relative.startswith('artifacts/')) or not path.resolve().is_relative_to(root.resolve()):raise ValueError('Invalid artifact path')
                        data=base64.b64decode(event['data'],validate=True)
                        if len(data)>2*1024*1024 or hashlib.sha256(data).hexdigest()!=event['sha256']:raise ValueError('Artifact integrity mismatch')
                        if path.is_symlink():raise ValueError('Symlink artifact refused')
                        path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
                    elif kind=='finished':finished=event['result'];break
                    elif kind=='fatal':raise RuntimeError(event.get('error','Worker failed'))
                if finished is None:raise RuntimeError('Worker connection ended without a completion receipt.')
            self._finish(run['id'],finished)
        except Exception as caught:
            error=str(caught)
            state='cancelled' if isinstance(caught,InterruptedError) else 'interrupted' if process is not None else 'blocked'
            self._finish(run['id'],{'state':state,'exit_code':None,'duration_seconds':min(run['timeout_seconds'],time.monotonic()-start),
                                     'warnings':['A missing completion receipt is not a successful experiment.']},error)
        finally:
            if process:
                try:
                    if process.stdin and not process.stdin.closed:process.stdin.close()
                    process.wait(timeout=3)
                except (OSError,subprocess.TimeoutExpired):
                    try:os.killpg(process.pid,signal.SIGTERM);process.wait(timeout=2)
                    except (OSError,subprocess.TimeoutExpired):
                        try:os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=2)
                        except (OSError,subprocess.TimeoutExpired):pass
                if process.stdout:process.stdout.close()
            if reader:reader.join(timeout=1)
            with self.lock:self.jobs.pop(run['id'],None)

    def close(self):
        with self.lock:
            if self._closed:return
            self._closed=True
        self.stop_event.set()
        if self.thread.is_alive():self.thread.join(timeout=2)
        with self.lock:
            jobs=list(self.jobs.values())
            for job in jobs:job['cancel'].set()
            with self.store._connect() as conn:queued=[r['id'] for r in conn.execute("SELECT id FROM experiment_runs WHERE state='queued'")]
            for run_id in queued:self._finish(run_id,{'state':'cancelled','exit_code':None,'duration_seconds':0},'Application shutdown')
        for job in jobs:
            job['thread'].join(timeout=10)
        self._lock_file.close()
