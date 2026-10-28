"""Bounded experiment supervisor, also sent verbatim to an SSH Python process.

One JSON request on stdin, then optional {"action":"cancel"}. Stdout is a JSON
protocol; child stdout/stderr remain raw bytes in files and base64 events.
This is process supervision, not an OS security sandbox for arbitrary code.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading
import time

MAX_LOG = 8 * 1024 * 1024
MAX_FILE = 2 * 1024 * 1024
MAX_ARTIFACTS = 20 * 1024 * 1024


def child_environment(devices, root):
    allowed = {'PATH','HOME','USER','LOGNAME','LANG','LC_ALL','TMPDIR','TMP','TEMP',
               'SSL_CERT_FILE','SSL_CERT_DIR','LD_LIBRARY_PATH','DYLD_LIBRARY_PATH',
               'HF_HOME','XDG_CACHE_HOME'}
    env = {k:v for k,v in os.environ.items() if k in allowed or k.startswith('_PYI_')}
    mode = 'cpu' if devices == ['cpu'] else 'mps' if all(d.startswith('metal:') for d in devices) else 'cuda'
    env.update(PYTHONUNBUFFERED='1', PYTHONIOENCODING='utf-8',
               CUDA_VISIBLE_DEVICES=','.join(devices) if mode=='cuda' else '',
               HIP_VISIBLE_DEVICES='', BRAINDANCE_DEVICE=mode,
               BRAINDANCE_GPU_IDS=','.join(devices), BRAINDANCE_RUN_DIR=str(root),
               BRAINDANCE_METRICS_PATH=str(root/'metrics.json'),
               BRAINDANCE_ARTIFACT_DIR=str(root/'artifacts'),
               OMP_NUM_THREADS='1', MKL_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1')
    return env


def terminate_group(process):
    if process is None: return
    try: os.killpg(process.pid,signal.SIGTERM)
    except ProcessLookupError: return
    try: process.wait(timeout=2)
    except subprocess.TimeoutExpired: pass
    try: os.killpg(process.pid,signal.SIGKILL)
    except ProcessLookupError: pass
    process.wait(timeout=3)


def run(spec):
    if os.name!='posix': raise ValueError('Experiment execution currently requires macOS or Linux.')
    if not re.fullmatch(r'[a-f0-9-]{36}',spec.get('run_id','')): raise ValueError('Invalid run ID')
    timeout=spec['timeout_seconds']
    if not isinstance(timeout,(int,float)) or isinstance(timeout,bool) or not 0<timeout<=86400:
        raise ValueError('Invalid timeout')
    root=(Path.home()/'.local/share/braindance/runs'/spec['run_id']) if spec['remote'] else Path(spec['run_dir'])
    root.mkdir(parents=True,exist_ok=True,mode=0o700)
    (root/'artifacts').mkdir(exist_ok=True)
    script=root/'experiment.py';script.write_text(spec['code'],encoding='utf-8')
    (root/'worker-spec.json').write_text(json.dumps(spec,ensure_ascii=False,indent=2),encoding='utf-8')
    cwd=Path(spec['cwd']).expanduser() if spec.get('cwd') else root
    if not cwd.is_dir(): raise ValueError('Working directory does not exist: '+str(cwd))
    lock=threading.Lock();cancel=threading.Event();log_limit=threading.Event()
    counts={'stdout':0,'stderr':0};truncated={'stdout':False,'stderr':False}
    def emit(event,**values):
        try:
            with lock:
                sys.stdout.write(json.dumps(dict(event=event,run_id=spec['run_id'],**values),ensure_ascii=False,allow_nan=False)+'\n')
                sys.stdout.flush()
        except (BrokenPipeError,OSError):
            cancel.set()
            raise
    def control():
        try:
            for line in sys.stdin:
                try:
                    if json.loads(line).get('action')=='cancel':cancel.set()
                except (ValueError,AttributeError):pass
        finally:cancel.set()  # A lost SSH/parent connection must not leave a job running.
    threading.Thread(target=control,daemon=True).start()
    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,lambda *_:cancel.set())
    interpreter=spec.get('interpreter','builtin')
    if interpreter=='builtin':
        command=[sys.executable]+(['--run-experiment'] if getattr(sys,'frozen',False) else [])
    else:command=[os.path.expanduser(interpreter)]
    command += [str(script),*spec.get('args',[])]
    env=child_environment(spec['device_ids'],root)
    env['BRAINDANCE_TIMEOUT_SECONDS']=str(timeout)
    deadline=min(time.time()+timeout,spec.get('deadline_epoch',float('inf')))
    env['BRAINDANCE_DEADLINE_UNIX']=str(deadline)
    if spec.get('cwd'):env['PYTHONPATH']=str(cwd)
    started=time.monotonic();process=None;threads=[]
    def pump(stream,name):
        with (root/('raw_'+name+'.log')).open('wb') as output:
            while True:
                chunk=stream.read1(8192)
                if not chunk:break
                available=max(0,MAX_LOG-counts[name]);kept=chunk[:available]
                if kept:
                    output.write(kept);output.flush();counts[name]+=len(kept)
                    try:emit('output',stream=name,data=base64.b64encode(kept).decode('ascii'))
                    except (BrokenPipeError,OSError):break
                if len(chunk)>available:
                    truncated[name]=True;log_limit.set()
    try:
        if time.time()>=deadline:raise TimeoutError('Research deadline passed before target execution')
        process=subprocess.Popen(command,cwd=str(cwd),env=env,stdin=subprocess.DEVNULL,
                                 stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
        emit('started',pid=process.pid,target_dir=str(root),device=env['BRAINDANCE_DEVICE'],digest=spec['digest'],
             code_sha256=hashlib.sha256(script.read_bytes()).hexdigest())
        for name in ('stdout','stderr'):
            thread=threading.Thread(target=pump,args=(getattr(process,name),name),daemon=True)
            thread.start();threads.append(thread)
        state=None;heartbeat=0
        while process.poll() is None:
            elapsed=time.monotonic()-started
            if log_limit.is_set():state='failed';break
            if cancel.is_set():state='cancelled';break
            if elapsed>=timeout or time.time()>=deadline:state='timed_out';break
            if elapsed-heartbeat>=1:emit('heartbeat',elapsed_seconds=elapsed);heartbeat=elapsed
            time.sleep(.05)
        terminate_group(process)
        for thread in threads:thread.join(timeout=4)
        state='failed' if log_limit.is_set() else state or ('succeeded' if process.returncode==0 else 'failed')
        warnings=[]
        if log_limit.is_set():warnings.append('Raw output exceeded the 8 MiB per-stream limit; the process was stopped. Truncation is recorded.')
        metrics=None;metric_path=root/'metrics.json'
        if metric_path.exists():
            try:
                if metric_path.is_symlink() or metric_path.stat().st_size>1024*1024:raise ValueError('metrics.json is a symlink or exceeds 1 MiB')
                metrics=json.loads(metric_path.read_text(encoding='utf-8'),parse_constant=lambda _:(_ for _ in ()).throw(ValueError('Nonfinite metric')))
                if not isinstance(metrics,dict):raise ValueError('metrics.json must contain an object')
            except (ValueError,OSError) as error:metrics=None;warnings.append(str(error))
        else:warnings.append('No metrics.json was produced; exit status is not a scientific result.')
        artifacts=[];transferred=0
        candidates=([metric_path] if metric_path.exists() else [])+list((root/'artifacts').rglob('*'))[:1000]
        for path in candidates:
            if not path.is_file():continue
            if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
                warnings.append('Skipped artifact outside the run directory: '+str(path));continue
            relative=path.relative_to(root).as_posix();size=path.stat().st_size
            item=dict(path=relative,size=size,target_path=str(path),transferred=not spec['remote'])
            if size<=MAX_FILE and transferred+size<=MAX_ARTIFACTS:
                data=path.read_bytes();item['sha256']=hashlib.sha256(data).hexdigest()
                emit('artifact',path=relative,size=len(data),sha256=item['sha256'],data=base64.b64encode(data).decode('ascii'))
                item['transferred']=True;transferred+=len(data)
            else:warnings.append('Artifact retained on target; exceeds transfer limit: '+relative)
            artifacts.append(item)
        result=dict(state=state,exit_code=process.returncode,duration_seconds=time.monotonic()-started,
                    metrics=metrics,artifacts=artifacts,warnings=warnings,log_bytes=counts,
                    log_truncated=truncated,target_dir=str(root),code_sha256=hashlib.sha256(spec['code'].encode()).hexdigest())
        (root/'worker-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
        emit('finished',result=result)
    finally:
        terminate_group(process)
        for stream in ('stdout','stderr'):
            if process and getattr(process,stream):getattr(process,stream).close()


def main():
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    try:
        line=sys.stdin.readline(512*1024)
        spec=json.loads(line)
        run(spec)
    except Exception as error:
        try:print(json.dumps(dict(event='fatal',error=str(error)),ensure_ascii=True),flush=True)
        except (BrokenPipeError,OSError):pass
        raise SystemExit(1)


if __name__=='__main__':main()
