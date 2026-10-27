"""Persistent, bounded research jobs. Display actual stages, never invented percent."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid

from tree_store import now

TERMINAL={'completed','failed','cancelled','interrupted'}


class ResearchEngine:
    def __init__(self,store,experiments=None):
        self.store=store;self.workspace=Path(store.db_path).parent
        from steering import initialize
        initialize(store)
        self.experiments=experiments
        self.root=self.workspace/'council-runs';self.root.mkdir(exist_ok=True,mode=0o700)
        self.lock=threading.RLock();self.closed=threading.Event();self.process=None;self.active_id=None
        self.lease=(self.root/'.research.lock').open('a+')
        import fcntl
        try:fcntl.flock(self.lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:self.lease.close();raise RuntimeError('이 작업공간의 연구 실행기가 이미 열려 있습니다.')
        with store._connect() as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS research_jobs (
                id TEXT PRIMARY KEY,project_id TEXT NOT NULL,node_id TEXT NOT NULL,
                title TEXT NOT NULL,state TEXT NOT NULL,phase TEXT NOT NULL,message TEXT NOT NULL,
                mode TEXT NOT NULL,config TEXT NOT NULL,run_dir TEXT NOT NULL,
                created_at TEXT NOT NULL,updated_at TEXT NOT NULL,finished_at TEXT,error TEXT
            )''')
            conn.execute("UPDATE research_jobs SET state='interrupted',message='이전 실행기가 종료됐습니다. 원본 로그를 확인한 뒤 새 실행을 시작하세요.',finished_at=?,updated_at=? WHERE state IN ('queued','running')",(now(),now()))
            conn.execute('CREATE TABLE IF NOT EXISTS research_analysis_queue (run_id TEXT PRIMARY KEY,state TEXT NOT NULL,job_id TEXT,error TEXT)')
        self.analysis_thread=None
        if experiments is not None:
            experiments.on_finished=self.queue_analysis
            with store._connect() as conn:
                for row in conn.execute("SELECT r.id,e.spec FROM experiment_runs r JOIN experiments e ON e.id=r.experiment_id WHERE r.state IN ('succeeded','failed','timed_out')"):
                    generation=json.loads(row['spec']).get('generation',{})
                    if generation and not generation.get('auto_session_id'):
                        conn.execute("INSERT OR IGNORE INTO research_analysis_queue VALUES(?,'pending',NULL,NULL)",(row['id'],))
            self.analysis_thread=threading.Thread(target=self._analysis_loop,daemon=True);self.analysis_thread.start()

    def availability(self):
        configured=os.environ.get('BRAINDANCE_ENGINE_DIR') or os.environ.get('ARIS_REPO')
        candidates=[Path.home()/'.local/share/BrainDance/research-engine',Path.home()/'aris_repo']
        aris=Path(configured).expanduser().resolve() if configured else next((p for p in candidates if (p/'skills/research-lit/SKILL.md').is_file()),candidates[-1]).resolve()
        checks={'Claude CLI':bool(shutil.which('claude')),'Codex CLI':bool(shutil.which('codex')),
                '논문 탐색 엔진':(aris/'skills/research-lit/SKILL.md').is_file(),
                '논문 확인 도구':(aris/'tools/verify_papers.py').is_file(),
                '독립 검토 연결':(aris/'mcp-servers/codex-exec/server.py').is_file()}
        return dict(available=all(checks.values()),chat_available=checks['Codex CLI'] and checks['독립 검토 연결'],missing=[k for k,v in checks.items() if not v],aris_repo=str(aris))

    @staticmethod
    def decode(row):
        item=dict(row);item['config']=json.loads(item['config']);return item

    def get(self,job_id):
        with self.store._connect() as conn:row=conn.execute('SELECT * FROM research_jobs WHERE id=?',(job_id,)).fetchone()
        if row is None:raise KeyError('연구 실행을 찾을 수 없습니다.')
        return self.decode(row)

    def list(self,project_id):
        with self.store._connect() as conn:
            if not conn.execute('SELECT id FROM projects WHERE id=?',(project_id,)).fetchone():raise KeyError('프로젝트를 찾을 수 없습니다.')
            rows=conn.execute('SELECT * FROM research_jobs WHERE project_id=? ORDER BY created_at DESC',(project_id,)).fetchall()
        return dict(jobs=[self.decode(r) for r in rows],availability={k:v for k,v in self.availability().items() if k!='aris_repo'})

    def info(self,job_id):
        item=self.get(job_id);root=Path(item['run_dir']);log=root/'progress.jsonl'
        registration=root/'registered-experiment.json'
        if registration.is_file():
            item['generated_experiment']=json.loads(registration.read_text())
        lines=[]
        if log.exists():
            for line in log.read_text()[-50000:].splitlines()[-100:]:
                try:lines.append(json.loads(line))
                except ValueError:pass
        item['events']=lines
        item['files']=[name for name in ['literature-request.txt','literature/LITERATURE.md','literature/source-evidence.json',
            'literature/verification.json','literature/verified-evidence.json','literature-usage.json',
            'council/usage.json','council/round-1/COUNCIL_REPORT.md','error.log',
            'worker.stderr.log','literature.stderr.log','verification.stderr.log','arxiv-fetch.stderr.log',
            'generated-experiment.py','generated-experiment.json','generated-proposal.json','environment.json','environment.stderr.log','context-discovery.json','resolved-context.json',
            'native-request.txt','native.stdout.jsonl','native.stderr.log','native-usage.json','native-skill-receipts.json','native-completion.json','scout-triage.json','scout-settings.json','scout-ideas.md','native-result-evidence.json','native-summary.md','advisory-ideas.md','advisory-results.md','registered-experiment.json','analysis.json','lab-usage.json','explored-environment.json',
            'exploration-1.json','exploration-2.json'] if (root/name).is_file()]
        for prefix in ['native-helpers','native-reviewer','native-code-review','scout-searches']:
            folder=root/prefix
            if folder.is_dir():item['files'].extend(str(p.relative_to(root)) for p in folder.glob('*/*') if p.is_file() and not p.is_symlink() and p.suffix in {'.json','.log','.txt'})
        reads=root/'target-reads'
        if reads.is_dir():item['files'].extend(str(p.relative_to(root)) for p in reads.iterdir() if p.is_file() and not p.is_symlink() and p.suffix in {'.json','.log'})
        # Bounded, known phase paths expose error diagnostics without arbitrary files.
        for phase in ['generation','peer-review','chairman']:
            folder=root/'council/round-1'/phase
            if folder.exists():
                item['files'].extend(str(p.relative_to(root)) for p in folder.glob('**/*.stderr.log') if p.is_file() and not p.is_symlink() and p.stat().st_size)
        return item

    def file(self,job_id,name):
        item=self.info(job_id);root=Path(item['run_dir']);path=root/name
        if name not in item['files'] or path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):raise KeyError('연구 파일을 찾을 수 없습니다.')
        return path

    def start(self,payload,internal=None):
        if set(payload)-{'node_id','mode','confirm','token_budget','phase_timeout_seconds','reuse_literature','task','run_id','context_path'} or payload.get('confirm') is not True:
            raise ValueError('연구 시작과 모델 사용량 발생을 확인하세요.')
        task=payload.get('task','research')
        if task not in {'research','draft','analyze','inspect','native'}:raise ValueError('지원하지 않는 연구 작업입니다.')
        context_path=payload.get('context_path','')
        if not isinstance(context_path,str) or len(context_path)>2048 or '\x00' in context_path or '\n' in context_path:raise ValueError('참고 폴더 경로를 확인하세요.')
        mode=payload.get('mode','balanced')
        if mode not in {'lite','balanced','deep'}:raise ValueError('지원하지 않는 연구 모드입니다.')
        node=self.store.get_node(payload.get('node_id'))
        if node['status'] not in {'active','expanded'}:raise ValueError('활성 노드에서 연구를 시작하세요.')
        if task=='research' and (node['kind']!='problem' or node['parent_id'] is not None):raise ValueError('프로젝트의 연구 문제 노드에서 시작하세요.')
        if task=='analyze':
            if not self.experiments:raise ValueError('실험 실행기가 연결되지 않았습니다.')
            run=self.experiments.run_info(payload.get('run_id',''))
            experiment=self.experiments.experiment(run['experiment_id'])
            if experiment['node_id']!=node['id'] or run['state'] not in {'succeeded','failed','timed_out'}:raise ValueError('분석할 완료 실험이 올바르지 않습니다.')
        token_budget=payload.get('token_budget',{'lite':250000,'balanced':500000,'deep':1000000}[mode])
        timeout=payload.get('phase_timeout_seconds',900)
        if type(token_budget) is not int or not 100000<=token_budget<=1000000:raise ValueError('Council 토큰 예산은 100000–1000000으로 입력하세요.')
        if type(timeout) is not int or not 60<=timeout<=1800:raise ValueError('단계별 제한 시간은 60–1800초로 입력하세요.')
        reuse=payload.get('reuse_literature',True)
        if type(reuse) is not bool:raise ValueError('근거 재사용 설정은 true 또는 false여야 합니다.')
        available=self.availability()
        if not available['available']:raise ValueError('설치가 필요합니다: '+', '.join(available['missing']))
        if not internal and task!='analyze':
            with self.store._connect() as conn:
                if conn.execute("SELECT 1 FROM sqlite_master WHERE name='automatic_sessions'").fetchone() and conn.execute("SELECT 1 FROM automatic_sessions WHERE project_id=? AND status='running'",(node['project_id'],)).fetchone():
                    raise ValueError('자동모드가 다음 작업을 관리 중입니다. 방향 수정 또는 일시정지를 사용하세요.')
        with self.lock,self.store._connect() as conn:
            if self.closed.is_set():raise ValueError('연구 실행기가 종료 중입니다.')
            old=conn.execute("SELECT * FROM research_jobs WHERE project_id=? AND state IN ('queued','running')",(node['project_id'],)).fetchone()
            if old:
                old=self.decode(old)
                if old['config'].get('task','research')!=task or (task=='analyze' and old['config'].get('run_id')!=payload.get('run_id')):
                    raise ValueError('이 프로젝트의 다른 작업이 진행 중입니다.')
                return old
            if self.active_id is not None:raise ValueError('다른 프로젝트가 연구 중입니다. 완료 또는 중지 후 시작하세요.')
            job_id=str(uuid.uuid4());root=self.root/job_id;root.mkdir(mode=0o700)
            topic=node['metadata'].get('research_goal') or node['metadata'].get('original_topic') or node['title']
            reusable=None
            if reuse:
                for prior in conn.execute('SELECT * FROM research_jobs WHERE project_id=? ORDER BY created_at DESC',(node['project_id'],)):
                    previous=json.loads(prior['config']);folder=Path(prior['run_dir'])
                    if previous.get('topic')==topic and (folder/'literature/verified-evidence.json').is_file() and (folder/'literature-usage.json').is_file():
                        reusable=dict(job_id=prior['id'],run_dir=str(folder));break
            config=dict(id=job_id,node_id=node['id'],project_id=node['project_id'],topic=topic,mode=mode,
                task=task,context_path=context_path,run_id=payload.get('run_id'),
                db=self.store.db_path,aris_repo=available['aris_repo'],literature_model='sonnet',
                claude_budget_usd=3 if mode=='lite' else 8,phase_timeout_seconds=timeout,
                reuse_literature=reusable,
                council_overrides=dict(rounds=1,max_councils=1,token_budget=token_budget,timeout_seconds=timeout,output_tokens=6000))
            from steering import prompt_context
            if task=='native':
                if not internal or not internal.get('auto_session_id'):raise ValueError('자율 파이프라인은 프로젝트 자동모드 권한이 필요합니다.')
                config['run_dir']=str(root);config['native_api']=self.api_url
            config['steering']=prompt_context(self.store,node['project_id'])
            from project_session import identity
            config['project_session']=identity(self.store,node['project_id'])
            if internal:
                config.update(internal)
                config['council_overrides']['session_budget']=internal['session_budget']
            if config['steering']['directions']:
                config['topic']+='\n사용자 방향 지시 (최신 지시가 상충하는 과거 지시보다 우선):\n'+json.dumps(config['steering']['directions'],ensure_ascii=False)
            if task!='inspect':conn.execute("UPDATE research_directions SET state='applied',job_id=? WHERE project_id=? AND seq<=?",(job_id,node['project_id'],config['steering']['revision']))
            from council import dump
            dump(root/'job.json',config)
            timestamp=now();record=dict(id=job_id,project_id=node['project_id'],node_id=node['id'],title=topic,
                state='queued',phase='preflight',message='연구 실행을 준비합니다.',mode=mode,config=config,
                run_dir=str(root),created_at=timestamp,updated_at=timestamp,finished_at=None,error=None)
            conn.execute('INSERT INTO research_jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',tuple(json.dumps(v,ensure_ascii=False) if k=='config' else v for k,v in record.items()))
            self.store._event(conn,node['id'],'research_started',{'job_id':job_id,'mode':mode})
            self.active_id=job_id
            self.cancel=threading.Event();self.thread=threading.Thread(target=self._execute,args=(record,),daemon=True)
        self.thread.start()
        return record

    def can_retry(self,record):
        root=Path(record['run_dir']);folder=root/'council'
        if record['state'] not in {'failed','interrupted'} or record['config'].get('task')!='research':return False
        failure=record.get('error') or record.get('message','')
        known='Token admission budget exhausted before dispatch' in failure
        recovered_input=record['config'].get('resume_existing') and 'Cannot resume Codex with changed input' in failure
        if not (known or recovered_input):return False
        if not all((folder/name).is_file() for name in ['config.json','run-inputs.json','run-state.json','usage.json','status.json']):return False
        return not json.loads((folder/'run-state.json').read_text()).get('tree_commit_started') and json.loads((folder/'status.json').read_text()).get('status')!='completed'

    def retry(self,job_id):
        """Resume an uncommitted Council admission stop, retaining calls and evidence."""
        with self.lock:
            record=self.get(job_id);self.store.get_node(record['node_id'])
            if self.closed.is_set() or self.active_id is not None or not self.can_retry(record):raise ValueError('이 작업은 기존 Council 호출을 안전하게 재개할 수 없습니다.')
            root=Path(record['run_dir'])
            if root.is_symlink() or root.absolute()!=self.root/record['id']:raise ValueError('관리되는 연구 폴더가 아닙니다.')
            config=dict(record['config'])
            if config.get('session_budget'):
                from session_budget import update
                update(config['session_budget'],'check')
            attempt=int(config.get('resume_attempt',0))+1;archive=root/'attempts'/str(attempt);archive.mkdir(parents=True)
            for name in ['job.json','progress.json','worker.stdout.log','worker.stderr.log','error.log','council/error.log']:
                source=root/name
                if source.is_file():
                    target=archive/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
            config.update(resume_existing=True,resume_attempt=attempt)
            from council import dump
            dump(root/'job.json',config);(root/'progress.json').unlink(missing_ok=True)
            record.update(config=config,state='queued',phase='preflight',message='완료된 Council 호출을 재사용해 중단 지점부터 이어갑니다.',finished_at=None,error=None)
            with self.store._connect() as conn:
                conn.execute('UPDATE research_jobs SET config=?,state=?,phase=?,message=?,finished_at=NULL,error=NULL,updated_at=? WHERE id=?',(json.dumps(config,ensure_ascii=False),record['state'],record['phase'],record['message'],now(),job_id))
                self.store._event(conn,record['node_id'],'research_retry',dict(job_id=job_id,attempt=attempt))
            self.active_id=job_id;self.cancel=threading.Event();self.thread=threading.Thread(target=self._execute,args=(record,),daemon=True)
        self.thread.start();return record

    def _update(self,job_id,data):
        state=data.get('state','running')
        if state not in {'queued','running',*TERMINAL}:return
        with self.store._connect() as conn:
            conn.execute('UPDATE research_jobs SET state=?,phase=?,message=?,updated_at=?,finished_at=?,error=? WHERE id=?',
                (state,data.get('phase','preflight'),data.get('message','')[:2000],data.get('updated_at',now()),now() if state in TERMINAL else None,
                 data.get('message') if state in {'failed','interrupted'} else None,job_id))

    def _execute(self,record):
        root=Path(record['run_dir']);progress=root/'progress.json';process=None;cancelled_at=None
        try:
            command=self.command()
            with (root/'worker.stdout.log').open('wb') as out,(root/'worker.stderr.log').open('wb') as err:
                with self.lock:
                    if self.cancel.is_set():raise InterruptedError()
                    process=subprocess.Popen(command+[str(root/'job.json')],stdout=out,stderr=err,start_new_session=True)
                    self.process=process
                self._update(record['id'],dict(state='running',phase='preflight',message='연구 환경을 확인합니다.'))
                start=time.monotonic();last=None
                while process.poll() is None:
                    if self.cancel.is_set() or self.closed.is_set() or not self._project_active(record):
                        self.cancel.set()
                        if cancelled_at is None:
                            cancelled_at=time.monotonic();os.killpg(process.pid,signal.SIGTERM)
                        elif time.monotonic()-cancelled_at>12:
                            os.killpg(process.pid,signal.SIGKILL)
                    if time.monotonic()-start>record['config']['phase_timeout_seconds']*7+300:
                        self.cancel.set()
                    if progress.exists():
                        try:
                            raw=progress.read_text()
                            if raw!=last:
                                pending=json.loads(raw)
                                # Worker completion is provisional until exit and host registration.
                                if pending.get('state')=='completed':
                                    pending={**pending,'state':'running','phase':'registering','message':'작업 종료 상태와 결과 등록을 확인합니다.'}
                                self._update(record['id'],pending);last=raw
                        except (OSError,ValueError):pass
                    time.sleep(.4)
                if progress.exists():
                    final=json.loads(progress.read_text())
                    if final.get('state') not in TERMINAL:
                        if self.cancel.is_set():raise InterruptedError()
                        raise RuntimeError('연구 완료 영수증 없이 프로세스가 종료됐습니다.')
                    if process.returncode!=0 and final.get('state')=='completed':raise RuntimeError('연구 종료 코드와 완료 영수증이 일치하지 않습니다.')
                    if final.get('state')=='completed' and (root/'generated-experiment.json').is_file():
                        final=self._register_generated(record,final)
                    self._update(record['id'],final)
                elif self.cancel.is_set():raise InterruptedError()
                else:raise RuntimeError('연구 실행 영수증이 없습니다. 원본 worker 로그를 확인하세요.')
        except BaseException as error:
            self._update(record['id'],dict(state='cancelled' if self.cancel.is_set() else 'failed',phase='stopped',message='연구를 중지했습니다.' if self.cancel.is_set() else str(error)[:2000]))
        finally:
            if process and process.poll() is None:
                try:os.killpg(process.pid,signal.SIGTERM);process.wait(timeout=12)
                except (ProcessLookupError,subprocess.TimeoutExpired):
                    try:os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=3)
                    except (ProcessLookupError,subprocess.TimeoutExpired):pass
            try:
                self.store.export_json(Path(self.store.db_path).with_suffix('.json'))
            finally:
                with self.lock:self.process=None;self.active_id=None

    def command(self):
        return [sys.executable,'--research-worker'] if getattr(sys,'frozen',False) else [sys.executable,'-u',str(Path(__file__).with_name('research_worker.py'))]

    def _register_generated(self,record,final):
        if not self.experiments:raise ValueError('생성 코드를 등록할 실험 실행기가 없습니다.')
        root=Path(record['run_dir']);data=json.loads((root/'generated-experiment.json').read_text());payload=data['payload']
        node=self.store.get_node(payload['node_id'])
        if node['project_id']!=record['project_id']:raise ValueError('생성 코드의 프로젝트가 일치하지 않습니다.')
        from experiments import resource_signature
        profile,assignment=self.experiments._resources(node)
        if data['target_signature']!=resource_signature(profile,assignment):raise ValueError('생성 중 실행 환경이 바뀌었습니다. 새 환경에서 다시 준비하세요.')
        if data['review'].get('verdict')!='pass':raise ValueError('코드 검토가 통과하지 않았습니다.')
        provenance=dict(job_id=record['id'],details=data['details'],checks=data['checks'],review=data['review'],automatic_analysis=True)
        config=record.get('config',{})
        provenance.update(direction_revision=config.get('steering',{}).get('revision',0))
        if config.get('auto_session_id'):provenance['auto_session_id']=config['auto_session_id']
        experiment=self.experiments.create(payload,provenance=provenance)
        from council import dump
        dump(root/'registered-experiment.json',dict(id=experiment['id'],digest=experiment['digest'],node_id=node['id']))
        message='자동모드 권한으로 검토된 LLM 실험을 실행 대기열에 등록합니다.' if config.get('auto_session_id') else 'LLM이 실행 코드와 내장 단위 검사를 준비했습니다. 실험 실행 탭에서 장치·예산을 확인하고 승인하세요.'
        return {**final,'phase':'experiment_approval','message':message}

    def queue_analysis(self,run_id):
        with self.store._connect() as conn:conn.execute("INSERT OR IGNORE INTO research_analysis_queue VALUES(?,'pending',NULL,NULL)",(run_id,))

    def _analysis_loop(self):
        while not self.closed.wait(.5):
            if self.active_id is not None:continue
            with self.store._connect() as conn:pending=[dict(r) for r in conn.execute("SELECT * FROM research_analysis_queue WHERE state='pending'")]
            for entry in pending:
                if self.closed.is_set() or self.active_id is not None:break
                try:
                    run=self.experiments.run_info(entry['run_id']);exp=self.experiments.experiment(run['experiment_id'])
                    if not exp['spec'].get('generation'):raise KeyError('Not an LLM-managed experiment')
                    if exp['spec']['generation'].get('native_session_id'):
                        with self.store._connect() as conn:conn.execute("UPDATE research_analysis_queue SET state='managed_native',error=NULL WHERE run_id=?",(run['id'],))
                        continue
                    if exp['spec']['generation'].get('auto_session_id'):raise KeyError('Automatic session owns this analysis')
                    job=self.start(dict(node_id=exp['node_id'],task='analyze',run_id=run['id'],confirm=True))
                    with self.store._connect() as conn:conn.execute("UPDATE research_analysis_queue SET state='dispatched',job_id=? WHERE run_id=?",(job['id'],run['id']))
                except ValueError:continue
                except (KeyError,OSError) as error:
                    with self.store._connect() as conn:conn.execute("UPDATE research_analysis_queue SET state='blocked',error=? WHERE run_id=?",(str(error),entry['run_id']))
                except Exception as error:
                    with self.store._connect() as conn:conn.execute("UPDATE research_analysis_queue SET state='blocked',error=? WHERE run_id=?",(type(error).__name__,entry['run_id']))

    def _project_active(self,record):
        try:return self.store.get_node(record['node_id'])['status'] in {'active','expanded'}
        except (KeyError,ValueError):return False

    def stop(self,job_id):
        item=self.get(job_id)
        with self.lock:
            if item['state'] not in TERMINAL and self.active_id==job_id:self.cancel.set()
        return item

    def close(self):
        self.closed.set()
        if self.analysis_thread and self.analysis_thread.is_alive():self.analysis_thread.join(timeout=2)
        if hasattr(self,'thread') and self.thread.is_alive():self.thread.join(timeout=18)
        self.lease.close()
