"""Bounded, incremental orchestration of the unmodified official paper verifier.

The upstream verifier decides identity/status and the aggregate verdict. Host
timeouts are only verify_pending, never evidence that a paper exists or is fake.
"""
from dataclasses import asdict
import hashlib
import importlib.util
import json
import os
import re
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import time

import council
from tree_store import now

RETRY_SECONDS=300
TTL_SECONDS=30*86400


def upstream(helper):
    digest=hashlib.sha256(helper.read_bytes()).hexdigest();name='_braindance_verifier_'+digest[:24]
    if name not in sys.modules:
        spec=importlib.util.spec_from_file_location(name,helper);module=importlib.util.module_from_spec(spec)
        sys.modules[name]=module
        try:spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(name,None);raise
    return sys.modules[name],digest


def check_active(job):
    if job.get('deadline_epoch') is not None and time.time()>=job['deadline_epoch']:raise InterruptedError('연구 종료 시각에 도달했습니다.')
    if job.get('auto_session_id') and job.get('db'):
        with sqlite3.connect(job['db'],timeout=3) as c:row=c.execute('SELECT status FROM automatic_sessions WHERE id=?',(job['auto_session_id'],)).fetchone()
        if not row or row[0]!='running':raise InterruptedError('프로젝트가 일시정지 또는 중지되었습니다. 검증 기록을 보존했습니다.')


def run_process(argv,folder,job,seconds,cwd):
    """Retain every raw attempt, and terminate its process group on timeout/stop."""
    check_active(job);started=time.monotonic();timed_out=False;code=None;process=None
    council.dump(folder/'attempt.json',dict(started_at=now(),timeout_seconds=seconds,argv=argv))
    try:
        with (folder/'stdout.log').open('wb') as out,(folder/'stderr.log').open('wb') as err:
            process=subprocess.Popen(argv,stdout=out,stderr=err,cwd=cwd,start_new_session=True)
            with council.PROCESS_LOCK:council.ACTIVE_PROCESSES.add(process)
            while process.poll() is None:
                check_active(job)
                if time.monotonic()-started>=seconds:timed_out=True;break
                time.sleep(.1)
            code=process.poll()
    finally:
        if process:
            if process.poll() is None:
                try:os.killpg(process.pid,signal.SIGTERM)
                except ProcessLookupError:pass
                try:process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    try:os.killpg(process.pid,signal.SIGKILL)
                    except ProcessLookupError:pass
                    process.wait(timeout=3)
            with council.PROCESS_LOCK:council.ACTIVE_PROCESSES.discard(process)
        council.dump(folder/'completion.json',dict(finished_at=now(),elapsed_seconds=time.monotonic()-started,exit_code=code,timed_out=timed_out))
    return code,timed_out


def run(job,root,work,candidates,progress,*,per_paper_seconds=25,total_seconds=120):
    root,work=Path(root),Path(work);helper=Path(job['aris_repo'])/'tools/verify_papers.py'
    official,helper_sha=upstream(helper)
    cache_dir=(Path(job['db']).parent if job.get('db') else root.parent.parent)/'paper-verification-cache'
    cache=official.load_cache(cache_dir/'verify_papers.json',30)
    # Host receipts stay outside the model-writable native research workspace.
    checkpoint=root/'verification-attempts';checkpoint.mkdir(exist_ok=True)
    started=time.monotonic();results=[];sources=[];verified=0
    def emit(message):
        if progress is not None:progress.emit('verification',message)
    for index,candidate in enumerate(candidates,1):
        check_active(job)
        paper=official.PaperInput(**candidate)
        key=hashlib.sha256(json.dumps(dict(paper=candidate,helper_sha256=helper_sha),sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        folder=checkpoint/key;folder.mkdir(exist_ok=True)
        saved=folder/'checkpoint.json';old=council.read_json(saved) if saved.is_file() else {}
        cached=cache.get(official.cache_key_for(paper),{})
        if cached.get('status') in {'verified','unverified','error'}:
            # This call contains cache hits only; upstream code performs no HTTP.
            result=official.verify_papers([paper],arxiv_batch_size=official.DEFAULT_BATCH_SIZE,fuzzy_threshold=official.DEFAULT_FUZZY_THRESHOLD,user_email='',cache=cache)[0]
            proof=folder/('official-cache-'+hashlib.sha256(json.dumps(cached,sort_keys=True).encode()).hexdigest()[:16]+'.json')
            if not proof.is_file():council.dump(proof,dict(helper_sha256=helper_sha,input=candidate,cache_entry=cached,result=asdict(result)))
            source=str(proof)
        elif old.get('input')==candidate and old.get('helper_sha256')==helper_sha and (old.get('retry_after',0)>time.time() or old.get('result',{}).get('status') in {'verified','unverified','error'} and old.get('completed_epoch',0)+TTL_SECONDS>time.time()):
            result=official.PaperResult(**old['result']);source=str(saved)
        else:
            left=total_seconds-(time.monotonic()-started)
            if job.get('deadline_epoch') is not None:left=min(left,job['deadline_epoch']-time.time())
            attempts=sorted(folder.glob('attempt-*'));attempt=folder/('attempt-'+str(len(attempts)+1));attempt.mkdir()
            council.dump(attempt/'input.json',[candidate]);output=attempt/'official-output.json'
            reason='host_verification_time_budget';raw=None
            emit(f'논문 존재 검증 {index-1}/{len(candidates)} · 확인 {verified}편 · {paper.id} 확인 중')
            if left>0:
                argv=council.python_command(helper)+['--input',str((attempt/'input.json').resolve()),'--output',str(output.resolve()),'--cache-dir',str((attempt/'official-cache').resolve())]
                # Independent attempt caches avoid concurrent writers to the shared upstream cache.
                code,timed_out=run_process(argv,attempt,job,min(per_paper_seconds,left),work)
                reason='host_per_paper_timeout' if timed_out else 'official_verifier_no_receipt'
                if code==0 and output.is_file():
                    try:
                        raw=council.read_json(output)['papers']
                        if len(raw)!=1 or raw[0].get('id')!=paper.id or raw[0].get('status') not in {'verified','unverified','verify_pending','error'}:raise ValueError('invalid official receipt')
                        result=official.PaperResult(**raw[0])
                    except (ValueError,KeyError,TypeError):raw=None;reason='official_verifier_invalid_receipt'
            if raw is None:result=official.PaperResult(id=paper.id,status='verify_pending',reason=reason)
            source=str(output if raw is not None else attempt/'input.json')
            council.dump(saved,dict(input=candidate,helper_sha256=helper_sha,result=asdict(result),source_receipt=source,completed_epoch=time.time(),retry_after=time.time()+RETRY_SECONDS if result.status=='verify_pending' else 0))
        results.append(result);sources.append(dict(id=paper.id,receipt=source))
        verified+=result.status=='verified'
        verdict,metrics=official.compute_verdict(results,official.DEFAULT_HALLUCINATION_WARN_THRESHOLD)
        # Commit after each paper, not after the slowest paper in a large batch.
        receipt=dict(verdict=verdict,**metrics,papers=[asdict(r) for r in results],host=dict(helper_sha256=helper_sha,checked_at=now(),incremental=True,completed=index,total=len(candidates),sources=sources))
        council.dump(work/'verification.json',receipt)
        council.dump(root/'paper-verification.json',receipt)
        emit(f'논문 존재 검증 {index}/{len(candidates)} · 확인 {verified}편 · 보류 {sum(r.status=="verify_pending" for r in results)}편')
    return receipt


def enrich(job,root,work,papers,progress):
    """Optional original abstracts: bounded and cached, never required to restart verification."""
    ids=sorted({p['arxiv_id'] for p in papers if isinstance(p.get('arxiv_id'),str) and re.fullmatch(r'\d{4}\.\d{4,5}(v\d+)?',p['arxiv_id'])})
    if not ids:return
    helper=Path(job['aris_repo'])/'tools/arxiv_fetch.py'
    if not helper.is_file():return
    key=hashlib.sha256(json.dumps(ids).encode()+helper.read_bytes()).hexdigest()
    base=Path(root)/'abstract-attempts'/key;base.mkdir(parents=True,exist_ok=True);memo=base/'checkpoint.json'
    old=council.read_json(memo) if memo.is_file() else {};source=Path(old['source']) if old.get('source') else None
    if old.get('retry_after',0)<=time.time() and (not old.get('success') or old.get('completed_epoch',0)+86400<=time.time()):
        if progress is not None:progress.emit('verification','원문 초록 조회 · 최대 20초 · 실패 시 보존된 읽기 근거로 검증을 계속합니다.')
        folder=base/('attempt-'+str(len(list(base.glob('attempt-*')))+1));folder.mkdir();source=folder/'stdout.log'
        seconds=20
        if job.get('deadline_epoch') is not None:seconds=min(seconds,max(.1,job['deadline_epoch']-time.time()))
        code,timed_out=run_process(council.python_command(helper)+['search','id:'+','.join(ids),'--max',str(len(ids))],folder,job,seconds,work)
        try:data=council.read_json(source);success=code==0 and not timed_out and isinstance(data,list) and bool(data)
        except (ValueError,OSError):success=False
        council.dump(memo,dict(source=str(source),success=success,completed_epoch=time.time(),retry_after=time.time()+RETRY_SECONDS if not success else 0))
    if source and source.is_file():
        try:
            data=council.read_json(source)
            if not isinstance(data,list):return
            abstracts={re.sub(r'v\d+$','',p['id']):p for p in data if isinstance(p,dict) and isinstance(p.get('id'),str)}
            for paper in papers:
                original=abstracts.get(re.sub(r'v\d+$','',paper.get('arxiv_id') or ''))
                if original and original.get('abstract') and original.get('abs_url'):paper.update(abstract=original['abstract'],title=original['title'],evidence_level='original_arxiv_abstract',url=original['abs_url'])
        except (ValueError,KeyError,TypeError):pass
