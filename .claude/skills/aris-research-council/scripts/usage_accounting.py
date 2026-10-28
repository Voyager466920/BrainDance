"""Invocation usage accounting, including cumulative Claude resume receipts.

Original provider reports stay intact. Cache traffic is not new uncached input.
"""
import json
from pathlib import Path

FIELDS=('input_tokens','output_tokens','cache_read_input_tokens','cache_creation_input_tokens')
CAMEL=('inputTokens','outputTokens','cacheReadInputTokens','cacheCreationInputTokens')


def zero():return dict.fromkeys(FIELDS,0)


def stream_usage(messages):
    return {k:sum(int(m.get(k,0) or 0) for m in messages.values() if isinstance(m,dict)) for k in FIELDS}


def model_usage(models):
    return {a:sum(int(m.get(b,0) or 0) for m in (models or {}).values() if isinstance(m,dict)) for a,b in zip(FIELDS,CAMEL)}


def total(value):return sum(value.get(k,0) for k in FIELDS)


def calculate(stream,models,baseline=None):
    """Use cumulative deltas only when a prior receipt and stream support them."""
    if not models:return stream,'per_invocation_stream'
    raw=model_usage(models)
    if baseline and total(raw)>=total(baseline):
        delta={k:max(0,raw[k]-baseline.get(k,0)) for k in FIELDS}
        # Large input/cache counters distinguish resumed cumulative stats from per-call resets.
        traffic=lambda x:sum(x.get(k,0) for k in FIELDS if k!='output_tokens')
        if traffic(delta)>=traffic(stream)*.98:return {k:max(delta[k],stream[k]) for k in FIELDS},'resumed_provider_delta'
    return {k:max(raw[k],stream[k]) for k in FIELDS},'provider_aggregate' if not baseline else 'provider_counter_reset'


def session_id(root):
    trace=Path(root)/'native.stdout.jsonl'
    if not trace.is_file():return None
    with trace.open() as stream:
        for line in stream:
            try:sid=json.loads(line).get('session_id')
            except ValueError:continue
            if sid:return sid
    return None


def prior_baseline(store,job,sid):
    if not sid:return None
    baseline=None;pending=zero()
    with store._connect() as conn:rows=conn.execute('SELECT id,config,run_dir FROM research_jobs WHERE project_id=? ORDER BY created_at,rowid',(job['project_id'],)).fetchall()
    for row in rows:
        if row['id']==job['id']:break
        cfg=json.loads(row['config'])
        if cfg.get('native_workspace')!=job['native_workspace'] or session_id(row['run_dir'])!=sid:continue
        receipt=Path(row['run_dir'])/'native-usage.json'
        if not receipt.is_file():continue
        d=json.loads(receipt.read_text())
        if d.get('model_usage'):baseline=model_usage(d['model_usage']);pending=zero()
        elif isinstance(d.get('usage'),dict):
            observed=stream_usage(d['usage']);pending={k:pending[k]+observed[k] for k in FIELDS}
    if baseline is None and not total(pending):return None
    return {k:(baseline or zero())[k]+pending[k] for k in FIELDS}


def reconcile(store,project_id):
    """Auditable local correction; never changes calls, device policy or run state."""
    from session_budget import update
    with store._connect() as conn:rows=conn.execute('SELECT id,config,run_dir FROM research_jobs WHERE project_id=? ORDER BY created_at,rowid',(project_id,)).fetchall()
    changes=[]
    for row in rows:
        cfg=json.loads(row['config']);path=Path(row['run_dir'])/'native-usage.json'
        if not path.is_file() or not cfg.get('session_budget') or not cfg.get('native_workspace'):continue
        d=json.loads(path.read_text())
        if d.get('accounting_version')==2:continue
        stream=stream_usage(d.get('usage') or {});sid=session_id(row['run_dir'])
        baseline=prior_baseline(store,{**cfg,'id':row['id'],'project_id':project_id},sid)
        observed,source=calculate(stream,d.get('model_usage'),baseline)
        before=d.get('tokens',0);after=total(observed)
        backup=path.with_name('native-usage.before-v2.json')
        if not backup.exists():backup.write_bytes(path.read_bytes())
        d.update(tokens=after,token_breakdown=observed,accounting_source=source,accounting_version=2,provider_aggregate_preserved=True)
        from council import dump
        update(cfg['session_budget'],'correct_observation',key=str(path),tokens=after,breakdown=observed,reason='Claude resumed modelUsage is cumulative; replace duplicate aggregate with invocation delta, preserving cache traffic and original receipt.')
        dump(path,d)
        changes.append(dict(job_id=row['id'],before=before,after=after,source=source))
    return changes
