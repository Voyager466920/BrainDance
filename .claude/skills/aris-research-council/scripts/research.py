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
    def __init__(self,store):
        self.store=store;self.workspace=Path(store.db_path).parent
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

    def availability(self):
        aris=Path(os.environ.get('ARIS_REPO',str(Path.home()/'aris_repo'))).expanduser().resolve()
        checks={'Claude CLI':bool(shutil.which('claude')),'Codex CLI':bool(shutil.which('codex')),
                'ARIS research-lit':(aris/'skills/research-lit/SKILL.md').is_file(),
                'ARIS verifier':(aris/'tools/verify_papers.py').is_file(),
                'ARIS Codex MCP':(aris/'mcp-servers/codex-exec/server.py').is_file()}
        return dict(available=all(checks.values()),missing=[k for k,v in checks.items() if not v],aris_repo=str(aris))

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
        lines=[]
        if log.exists():
            for line in log.read_text()[-50000:].splitlines()[-100:]:
                try:lines.append(json.loads(line))
                except ValueError:pass
        item['events']=lines
        item['files']=[name for name in ['literature-request.txt','literature/LITERATURE.md','literature/source-evidence.json',
            'literature/verification.json','literature/verified-evidence.json','literature-usage.json',
            'council/usage.json','council/round-1/COUNCIL_REPORT.md','error.log',
            'worker.stderr.log','literature.stderr.log','verification.stderr.log','arxiv-fetch.stderr.log'] if (root/name).is_file()]
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

    def start(self,payload):
        if set(payload)-{'node_id','mode','confirm','token_budget','phase_timeout_seconds','reuse_literature'} or payload.get('confirm') is not True:
            raise ValueError('연구 시작과 모델 사용량 발생을 확인하세요.')
        mode=payload.get('mode','balanced')
        if mode not in {'lite','balanced','deep'}:raise ValueError('지원하지 않는 연구 모드입니다.')
        node=self.store.get_node(payload.get('node_id'))
        if node['status'] not in {'active','expanded'}:raise ValueError('활성 노드에서 연구를 시작하세요.')
        if node['kind']!='problem' or node['parent_id'] is not None:raise ValueError('프로젝트의 연구 문제 노드에서 시작하세요.')
        token_budget=payload.get('token_budget',{'lite':250000,'balanced':500000,'deep':1000000}[mode])
        timeout=payload.get('phase_timeout_seconds',900)
        if type(token_budget) is not int or not 100000<=token_budget<=1000000:raise ValueError('Council 토큰 예산은 100000–1000000으로 입력하세요.')
        if type(timeout) is not int or not 60<=timeout<=1800:raise ValueError('단계별 제한 시간은 60–1800초로 입력하세요.')
        reuse=payload.get('reuse_literature',True)
        if type(reuse) is not bool:raise ValueError('근거 재사용 설정은 true 또는 false여야 합니다.')
        available=self.availability()
        if not available['available']:raise ValueError('설치가 필요합니다: '+', '.join(available['missing']))
        with self.lock,self.store._connect() as conn:
            if self.closed.is_set():raise ValueError('연구 실행기가 종료 중입니다.')
            old=conn.execute("SELECT * FROM research_jobs WHERE project_id=? AND state IN ('queued','running')",(node['project_id'],)).fetchone()
            if old:return self.decode(old)
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
                db=self.store.db_path,aris_repo=available['aris_repo'],literature_model='sonnet',
                claude_budget_usd=3 if mode=='lite' else 8,phase_timeout_seconds=timeout,
                reuse_literature=reusable,
                council_overrides=dict(rounds=1,max_councils=1,token_budget=token_budget,timeout_seconds=timeout,output_tokens=6000))
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
                            if raw!=last:self._update(record['id'],json.loads(raw));last=raw
                        except (OSError,ValueError):pass
                    time.sleep(.4)
                if progress.exists():
                    final=json.loads(progress.read_text())
                    if final.get('state') not in TERMINAL:
                        if self.cancel.is_set():raise InterruptedError()
                        raise RuntimeError('연구 완료 영수증 없이 프로세스가 종료됐습니다.')
                    if process.returncode!=0 and final.get('state')=='completed':raise RuntimeError('연구 종료 코드와 완료 영수증이 일치하지 않습니다.')
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
            with self.lock:self.process=None;self.active_id=None
            self.store.export_json(Path(self.store.db_path).with_suffix('.json'))

    def command(self):
        return [sys.executable,'--research-worker'] if getattr(sys,'frozen',False) else [sys.executable,'-u',str(Path(__file__).with_name('research_worker.py'))]

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
        if hasattr(self,'thread') and self.thread.is_alive():self.thread.join(timeout=18)
        self.lease.close()
