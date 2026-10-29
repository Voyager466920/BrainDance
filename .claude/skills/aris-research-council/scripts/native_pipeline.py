"""Official research-pipeline executor with bounded host tools; no replacement loop.

ARIS owns discovery, implementation, debugging and review decisions. The host
only supplies Council advice, its existing execution broker, and durable receipts.
"""
import argparse
import codecs
from contextlib import redirect_stdout
import hashlib
import json
import os
from pathlib import Path
import selectors
import shutil
import signal
import subprocess
import sys
import time
from types import SimpleNamespace

import council
from tree_store import TreeStore,now

SKILLS=('research-pipeline','idea-discovery','experiment-bridge','auto-review-loop','novelty-check')
HELPERS={'run_state.py','iteration_log.py','arxiv_fetch.py','verify_papers.py','provenance.py','evidence_check.py'}


def workspace(job):return Path(job['native_workspace']).resolve()


def freeze_advisory(work, stage, literature, evidence, topic, config):
    """Bind resume to scientific inputs, never volatile verifier receipt metadata.

    Keep the full raw verification receipt at its original path. Council receives
    the same checked paper content at an immutable path on every retry.
    """
    papers=council.read_json(evidence)['papers']
    content=dict(papers=papers)
    binding=dict(literature=literature.read_text(),evidence=content,topic=topic,config=config)
    fingerprint=hashlib.sha256(json.dumps(binding,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    folder=Path(work)/('council-'+stage+'-'+fingerprint+'-frozen-v2')
    inputs=Path(work)/'council-inputs'/fingerprint
    inputs.mkdir(parents=True,exist_ok=True)
    for name,text in [('LITERATURE.md',binding['literature']),('evidence.json',json.dumps(content,sort_keys=True,ensure_ascii=False,indent=2)),('topic.txt',topic)]:
        path=inputs/name
        if path.exists():
            if path.read_text()!=text:raise ValueError('Frozen Council input changed: '+name)
        else:
            with path.open('x',encoding='utf-8') as output:output.write(text)
    return folder,inputs,fingerprint


def review_directory(root,spec,revision,signature):
    binding=json.dumps(dict(spec=spec,revision=revision,resource_signature=signature),sort_keys=True,ensure_ascii=False)
    return Path(root)/'native-code-review'/hashlib.sha256(spec['code'].encode()).hexdigest()/hashlib.sha256(binding.encode()).hexdigest()[:20]


def install(job):
    repo=Path(job['aris_repo']);work=workspace(job);work.mkdir(parents=True,exist_ok=True,mode=0o700)
    plugin=work/'.aris-official';plugin.mkdir(exist_ok=True)
    for name in SKILLS:
        if not (repo/'skills'/name/'SKILL.md').is_file():raise FileNotFoundError('공식 파이프라인 Skill이 없습니다: '+name)
    manifest={str(p.relative_to(repo)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (repo/'skills').rglob('*') if p.is_file() and not p.is_symlink() and '__pycache__' not in p.parts}
    receipt=plugin/'source-manifest.json'
    if receipt.exists():
        if council.read_json(receipt)!=manifest:raise ValueError('실행 중 원본 Skills가 변경되었습니다. 기존 작업공간을 보존하고 새 실행을 시작하세요.')
    else:
        shutil.copytree(repo/'skills',plugin/'skills',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        shutil.copytree(repo/'tools',plugin/'tools',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        (plugin/'.claude-plugin').mkdir()
        council.dump(plugin/'.claude-plugin/plugin.json',dict(name='aris-official',version='1.0.0'))
        council.dump(receipt,manifest)
    return work,plugin


def command(flag,*args):
    return [sys.executable,flag,*map(str,args)] if getattr(sys,'frozen',False) else [sys.executable,str(Path(__file__).resolve()),flag,*map(str,args)]


CONTRACT='''You are the main autonomous BrainDance research executor. Invoke Skill aris-official:research-pipeline; follow its real idea-discovery -> experiment-bridge -> auto-review-loop -> summary workflow. AUTO_PROCEED=true, HUMAN_CHECKPOINT=false, AUTO_WRITE=false, COMPACT=true. ARIS owns implementation, debugging, interpretation and next-experiment decisions; do not replace its loop with a different staged planner. Load its actual nested Skills with the Skill tool at their boundaries. Existing measured results and completed stage artifacts remain reusable: loading a missing Skill is not permission to discard them or rerun a completed experiment. Use sequential fallback where Agent is unavailable.
Keep the normal ARIS Reviewer: call mcp__codex__codex for its independent novelty/code/result reviews, then implement its feedback and re-review per the original Skill. Council is ADDITIONAL ADVICE, not the Reviewer or its stop/quality gate. Call mcp__codex__council(stage=ideas) after literature/idea discovery and before the first experiment; call stage=results after measured results, before the next experiment and final summary. Council advice can be challenged with evidence; retain disagreement. Do not repeat an identical reviewer question just to fill a stage.
HOST TOOL ADAPTATION ONLY: Bash/SSH/Agent are unavailable in this managed session. Use mcp__codex__helper for the real upstream Python bookkeeping helpers; mcp__codex__target for read-only existing target inventory/source reads. Read/Write/Edit operate on this dedicated local project workspace. For all pilots, sanity checks, real experiments, retries and ablations use mcp__codex__experiment. It applies the already selected local/SSH device UUID, current direction, code review, run count and cumulative runtime budget. Never execute model code through a helper or call an external shell. No package installation, GPU reassignment or budget changes. Missing prerequisites should be investigated through target reads and repaired in experiment source where possible; do not invent interfaces or results.
Write a self-contained Python source file defining self_test() with real assertions and run_experiment(); omit __main__ (host appends it). Use the observed Python interpreter, existing project/data paths, BRAINDANCE_DEVICE/CUDA_VISIBLE_DEVICES, BRAINDANCE_METRICS_PATH and BRAINDANCE_ARTIFACT_DIR. Metrics JSON: baseline/candidate objects with the exact metric key. Experiment source can import the existing target repository. The experiment tool itself performs the original Reviewer code-review check; do not ask an identical extra code-review question before submitting the same source. The tool returns a real queued run; poll with mcp__codex__receipt and use its exit state/metrics/logs to debug and continue yourself. A rejected code review or failed execution is feedback to fix and resubmit, not a forced whole-project stop. Diagnose missing modules by checking existing observed Python environments before changing the experiment. Failed attempts do not consume the measured-experiment quota; they still consume actual runtime and model usage. Continue debugging within existing limits without asking the human for each repair. Negative but correctly measured results are valid completed experiments; never keep retrying just to obtain a positive scientific result.
For native crashes (e.g. SIGABRT), inspect the retained fatal-signal stack and failing operation before changing scientific conditions. If repeated simulator/renderer initialization is implicated, consider bounded foreground child processes in the same supervised process group. Preserve the specified seeds, initial states, controls and measurements; save per-trial data atomically and retain child logs, return codes, unresolved IDs and actual termination reasons. Never silently omit crashed trials, rename an undefined metric into a successful result, or treat a passing self-test as a completed scientific experiment.
For the literature Council input, write LITERATURE.md plus source-evidence.json {papers:[{id,title,url,arxiv_id,doi,source_excerpt,evidence_level,verification_status}]} and candidate_papers.json array with matching ids. Only retrieved readable evidence; unknown ids=null. Council invokes the actual upstream verifier before admitting sources. Preserve source text, original traces and limitations.
Call mcp__codex__context at the start and before every new experiment to receive the SAME shared project conversation, latest human directions, remaining budget and selected target. Changes govern the next immutable experiment; experiments in flight keep their exact source. Pause/stop/resource changes are enforced by the host. All responses and reports in Korean, using BrainDance branding; internal Skill identifiers belong in technical traces. Original identifiers/quotations remain intact.
When the native review loop reaches its own stopping condition or the allowed experiment count is reached, write NARRATIVE_REPORT.md from actual receipts, record limitations, and call mcp__codex__finish(report='NARRATIVE_REPORT.md'). Do not declare completion without real execution, both Council advice stages, and real ARIS Reviewer calls. Resume the stored native session and upstream .aris/runs state after interruption; never mark unfinished stages successful. Read the source-manifest for provenance, never edit .aris-official.
'''


def session_skill_receipts(job):
    """Reuse actual successful Skill receipts within this automatic research session."""
    store=TreeStore(job['db']);invoked=set();sources=[];pending_finish=None
    with store._connect() as conn:
        rows=conn.execute('SELECT id,config,run_dir,state,error,message FROM research_jobs WHERE project_id=? ORDER BY created_at',(job['project_id'],)).fetchall()
    for row in rows:
        config=json.loads(row['config'])
        if config.get('auto_session_id')!=job.get('auto_session_id') or config.get('native_workspace')!=job.get('native_workspace') or config.get('native_cycle',0)!=job.get('native_cycle',0) or config.get('hypothesis_task_id')!=job.get('hypothesis_task_id') or config.get('task_role','single')!=job.get('task_role','single'):continue
        trace=Path(row['run_dir'])/'native.stdout.jsonl'
        if not trace.is_file():continue
        requested={};succeeded=set();finish_request=None
        for line in trace.read_text().splitlines():
            try:event=json.loads(line)
            except ValueError:continue
            content=(event.get('message') or {}).get('content',[])
            for block in content if isinstance(content,list) else []:
                if block.get('type')=='tool_use' and block.get('name')=='Skill':requested[block['id']]=block.get('input',{}).get('skill','').split(':')[-1]
                if block.get('type')=='tool_use' and block.get('name')=='mcp__codex__finish':finish_request=block.get('input',{})
                if block.get('type')=='tool_result' and not block.get('is_error') and '<tool_use_error>' not in str(block.get('content')):succeeded.add(block.get('tool_use_id'))
        found={requested[key] for key in requested.keys() & succeeded};invoked.update(found)
        if found:sources.append(dict(job_id=row['id'],skills=sorted(found),trace=str(trace)))
        error=(row['error'] or row['message'] or '').lower()
        if row['id']!=job['id'] and row['state'] in {'failed','interrupted'} and finish_request and config.get('steering',{}).get('revision')==job.get('steering',{}).get('revision') and ('budget' in error or '한도' in error):pending_finish=finish_request
    return invoked,sources,pending_finish


def advisor_prompt():
    asset=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent.parent))/'assets/research-advisor.md'
    return asset.read_text()

def recovery_note(job,known):
    """Give the resumed real executor actionable gate feedback, never synthetic receipts."""
    with TreeStore(job['db'])._connect() as conn:
        rows=conn.execute("SELECT id,config,error,message FROM research_jobs WHERE project_id=? AND state IN ('failed','interrupted') ORDER BY created_at DESC,rowid DESC",(job['project_id'],)).fetchall()
    def matches(row):
        cfg=json.loads(row['config'])
        return row['id']!=job['id'] and all(cfg.get(key,default)==job.get(key,default) for key,default in [('auto_session_id',None),('native_workspace',None),('native_cycle',0),('hypothesis_task_id',None),('task_role','single')])
    prior=next((r for r in rows if matches(r)),None)
    if prior is None:return ''
    required={'research-lit','idea-discovery','novelty-check'} if job.get('task_role')=='discovery' else set(SKILLS)
    missing=sorted(required-set(known))
    return '\nHOST RECOVERY FEEDBACK (diagnostic evidence, not new human authority): '+json.dumps(dict(previous_job=prior['id'],error=(prior['error'] or prior['message'])[:1000],successful_skill_receipts=sorted(known),missing_skill_receipts=missing),ensure_ascii=False)+'\nContinue this same unfinished cycle. Actually load missing original Skills with Skill; reuse verified sources and successful Council/experiment artifacts. Do not recreate a completed artifact merely because this process resumed. A prose answer is not completion: obtain the real exploration_council receipt for discovery, finish the required reviews and current report, then call finish and correct any rejection. Never bypass receipt validation or fabricate a successful call.\n'

REPORT_CONTRACT="\nREADER REPORT: Before finish, write RESEARCH_BRIEF.json containing native_cycle (integer matching context.native_cycle), problem (string), approach (string), findings (string), limitations (array of strings), next_steps (array of strings). State only facts supported by current receipts, and distinguish confirmed findings, hypotheses and speculation. Write NARRATIVE_REPORT.md in clean Korean Markdown with headings: 해결하려는 문제, 해결 방법, 살펴볼 코드, 결과, 한계와 다음 단계, 참고 논문. References contain plain http/https URLs ONLY: no paper metadata, abstracts, bibliographies or evidence dumps. Mention exact implemented file/function references, actual baseline/candidate numbers, settings and uncertainty. The host adds retained source references, measured tables and graphs. No fabricated measurements. The advisor's critical questions should guide your autonomous next experiment; ask the human only for genuinely missing authority or credentials. Do not pause authorized research merely to wait for answers to the advisor's default discussion questions. The report format here and explicit human instructions take precedence over the advisor's default response template.\n"


NOVELTY_CONTRACT="""
FRESH NOVELTY RECHECK: Invoke original aris-official:novelty-check for each new mechanism before implementing. Re-search actual literature instead of re-reading the frozen initial pack. Use novelty_check(hypothesis, queries=[at least 3 distinct targeted searches]); the host searches both installed source clients without date filters, re-verifies paper existence with --no-cache, and obtains the original independent Reviewer novelty comparison. This tool supplies the original Skill's source/verification/reviewer slot; do not repeat an identical Reviewer call. Attach its novelty_receipt when registering scout_candidates. State closest prior work, concrete mechanism-level delta and coverage limits. Never equate an existing ID, a new combination of keywords, better measurements, or no search hits with proven novelty. If sources cannot be checked, say unverified; feasibility pilots may continue with that label. Council separately re-searches its actual generated proposals before anonymous review. Preserve all original receipts and errors.
"""


DISCOVERY_CONTRACT="""You are the BrainDance broad discovery coordinator, before the official per-hypothesis research pipeline. Load the unmodified aris-official:research-lit and idea-discovery Skills. Use paper_search for real 3–5 year trend and cross-field source retrieval, including older foundational prior art; vary the fields between rounds using shared negative results. Write LITERATURE.md/source-evidence.json/candidate_papers.json, then call exploration_council once: it supplies SIX independent isolated exploratory agents by default (trends, problem discovery, cross-field transfer, new principles, adversarial alternatives, falsifiable pilots). Synthesize FIVE diverse concrete hypotheses; do not pad the count if evidence is insufficient. Use the original novelty-check Skill and novelty_check tool to re-search and independently review each shortlisted mechanism. When interests are empty use context.discovery_interest. Register hypotheses with scout_candidates, including novelty_receipt and ratings={potential,novelty_provisional,feasibility,falsifiability} (integers 0–100) and rating_basis. Scores are reasoned provisional judgments, not measured probabilities; unverified novelty remains explicitly provisional. Prefer a new problem, structural insight or mechanism over a simple combination/performance tweak. Shortlist normally TWO, up to five only with evidence and useful execution capacity. Finish with node_ids=[shortlisted IDs], report='NARRATIVE_REPORT.md'. This finishes discovery ONLY, not scientific verification. The host gives EACH hypothesis its own workspace, native session and unmodified official research-pipeline. Do not run experiments here or write experimental code. Original ARIS research-pipeline, experiment-bridge, auto-review-loop, implementation, debugging and reporting run inside those separate studies. Keep project human conversation shared. References in readable reports are URLs only. No human selection checkpoint during authorized automatic mode.
"""

STUDY_CONTRACT="""
This is ONE independent preliminary study, not the broad discovery coordinator. Read HYPOTHESIS.json. Invoke the unmodified official aris-official:research-pipeline for this selected problem/hypothesis, preserving its idea-discovery, experiment-bridge, original Reviewer, auto-review-loop, debugging and summary. Reuse supplied literature as a starting point, check it, refine the selected hypothesis without switching to unrelated topics. ARIS authors real experiment source itself. Report this study's observations, failures and limitations in its own NARRATIVE_REPORT.md and RESEARCH_BRIEF.json. Other tasks' results are shared context, never this task's measured receipts. Original ARIS Reviewer and its internal loops remain required. Exploratory advice, if supplied, is context rather than validation. If HYPOTHESIS.json marks human_requested, no broad-discovery receipt is implied: verify the requested hypothesis and prior art through the original pipeline before experiment implementation; the extra full Council is optional for ideas and negative preliminary results, required for a promising measured pilot before final reporting. Avoid repeating broad ideation inside this fixed study. The project host starts other hypotheses/new discovery after your completed study; do not force this one hypothesis to run until the global deadline or fabricate a positive outcome.
"""
STUDY_CONTRACT+='\nPRE-EXPERIMENT REJECTION: If actual prior-art comparison shows duplication, insufficient contribution or a genuinely infeasible premise, load the original novelty-check Skill and ask the existing independent codex Reviewer for an explicit disposition. Do not run a meaningless GPU experiment just to satisfy completion. After its justified reject decision, write a report and call finish(outcome="rejected", rejection_kind="duplicate"|"low_novelty"|"infeasible", reason=<specific reason>, report=<path>). The Reviewer must provide disposition="reject", matching rejection_kind, rationale, evidence_urls (actual compared paper URLs required for duplicate/low_novelty). Missing searches or low scores alone are not proof of duplication; temporary tool/auth/dependency errors are not scientific rejection. This closes only this hypothesis, with no measured-result claim; the project continues other work until its original deadline.\n'


def run(job,root,progress):
    work,plugin=install(job)
    known,sources,pending_finish=session_skill_receipts(job)
    if pending_finish:
        try:completed=Host(job).execute('finish',dict(pending_finish))
        except (ValueError,RuntimeError,OSError,KeyError):pass
        else:
            council.dump(root/'native-completion.json',completed);council.dump(root/'native-skill-receipts.json',dict(invoked=sorted(known),source_jobs=sources,reused=True));council.dump(root/'native-usage.json',dict(model=job['literature_model'],messages=0,tokens=0,replayed_local_finish=True))
            progress.emit('native-completed','기존 모델의 보고 요청을 재사용해 검증된 결과를 저장했습니다. 추가 모델 호출은 없습니다.',state='completed');return
    host=command('--native-host',str(root/'job.json'))
    mcp=work/'.host-mcp.json';council.dump(mcp,dict(mcpServers={'codex':dict(command=host[0],args=host[1:])}))
    contract=CONTRACT+REPORT_CONTRACT+NOVELTY_CONTRACT
    if job.get('task_role')=='discovery':
        human=(Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent.parent))/'assets/broad-exploration.md').read_text().replace('[연구 분야/관심 주제]',job['topic'])
        contract=human+'\n'+DISCOVERY_CONTRACT+NOVELTY_CONTRACT
    elif job.get('hypothesis_task_id'):contract+=STUDY_CONTRACT
    if job.get('research_style')=='scout' and job.get('task_role')!='discovery':
        from scout import CONTRACT as scout_contract
        contract+='\n'+scout_contract
        council.dump(root/'scout-settings.json',job.get('scout_preferences',{}))
    from session_budget import time_only,deadline_for
    continuous=time_only(job)
    if continuous:
        contract+='\nTIME-ONLY CONTINUOUS RESEARCH: The human authorized research until the absolute deadline '+str(deadline_for(job))+'. There are NO project model-call, token, dollar or experiment-count caps. Usage is still recorded. context.max_runs=null means unlimited; do not stop because of previous numeric defaults. Follow the official pipeline and its artifact-driven internal review loop, not a timer-based fresh review. Finish each scientifically coherent cycle with its real reviewed report using finish; the host then continues the next exploration cycle automatically until the deadline. A successful or negative experiment is information, not permission to terminate the whole project. Explore the next unresolved hypothesis or a new cross-field connection; preserve failures and avoid repeating unchanged completed pilots. When the host says a new cycle starts, create a NEW upstream pipeline run in the SAME shared project conversation/workspace, reusing evidence and reviewer context appropriately.\n'
    (work/'CLAUDE.md').write_text(contract)
    statefile=work/'native-session.json';state=council.read_json(statefile) if statefile.exists() else {}
    from usage_accounting import prior_baseline,stream_usage,calculate,total as usage_total
    usage_baseline=prior_baseline(TreeStore(job['db']),job,state.get('session_id'))
    argv=['claude','-p','--verbose','--output-format','stream-json','--model',job['literature_model'],
          '--append-system-prompt',advisor_prompt(),'--plugin-dir',str(plugin),'--restricted','--setting-sources','project','--strict-mcp-config','--mcp-config',str(mcp),
          '--permission-mode','acceptEdits','--permission-prompts','none',
          '--tools','Skill,Read,Write,Edit,Glob,Grep,WebSearch,WebFetch',
          '--allowedTools','Skill,Read,Write,Edit,Glob,Grep,WebSearch,WebFetch,mcp__codex__*',
          '--disallowedTools','Bash,Agent']
    if not continuous:argv+=['--max-turns',str(job.get('native_max_turns',120)),'--max-budget-usd',str(job.get('native_usd_limit',8))]
    if state.get('session_id'):argv+=['--resume',state['session_id']]
    council.dump(root/'native-argv.json',argv)
    prompt=contract+'\nResearch direction (human authority):\n'+job['topic']+'\nAuthorized automatic run id: '+job['auto_session_id']+'; current scientific cycle: '+str(job.get('native_cycle',0))+'. Reuse the upstream run state only when resuming THIS unfinished cycle. If the prior cycle is complete, begin a NEW upstream pipeline run and a new research question while preserving all prior reports.\nBegin by reading host context. Continue until the native pipeline cycle completes or a real host deadline/stop prevents progress.'+recovery_note(job,known)
    (root/'native-request.txt').write_text(prompt)
    (root/'advisor-system-prompt.md').write_text(advisor_prompt())
    from session_budget import update
    key=str(root/'native-usage.json');update(job['session_budget'],'reserve',key=key,calls=1,estimate=50000)
    messages={};requested={};succeeded=set();results=[];reserved=1;finish_ids=set();host_finished=False
    progress.emit('native-pipeline','메인 연구 세션이 공식 자율 파이프라인을 실행합니다.')
    env=os.environ.copy();env['ARIS_REPO']=str(Path(job['aris_repo']).resolve());env['CLAUDE_CODE_MAX_OUTPUT_TOKENS']='7000'
    with (root/'native.stdout.jsonl').open('w') as out,(root/'native.stderr.log').open('w') as err:
        p=subprocess.Popen(argv,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=err,cwd=work,env=env,text=True,start_new_session=True)
        with council.PROCESS_LOCK:council.ACTIVE_PROCESSES.add(p)
        try:
            p.stdin.write(prompt);p.stdin.close();selector=selectors.DefaultSelector();selector.register(p.stdout,selectors.EVENT_READ)
            pending='';decoder=codecs.getincrementaldecoder('utf-8')();start=time.monotonic();last_event=None
            # Read bytes: TextIO.readline can hide already-buffered records from select.
            os.set_blocking(p.stdout.fileno(),False)
            while p.poll() is None or selector.get_map():
                update(job['session_budget'],'check')
                if not continuous and time.monotonic()-start>job['phase_timeout_seconds']*7:raise TimeoutError('공식 연구 세션 제한 시간을 초과했습니다.')
                for keyevent,_ in selector.select(.2):
                    block=os.read(keyevent.fd,65536)
                    if not block:selector.unregister(keyevent.fileobj);continue
                    pending+=decoder.decode(block)
                    while '\n' in pending:
                        line,pending=pending.split('\n',1);out.write(line+'\n');out.flush()
                        try:row=json.loads(line)
                        except ValueError:continue
                        if row.get('session_id'):council.dump(statefile,dict(session_id=row['session_id'],updated_at=now()))
                        msg=row.get('message') or {}
                        if row.get('type')=='assistant' and msg.get('id'):
                            ident=msg['id']
                            if ident not in messages and len(messages)>=reserved:
                                update(job['session_budget'],'reserve',key=str(root/'native-usage.json'),calls=1,estimate=0);reserved+=1
                            messages[ident]=msg.get('usage',{})
                            total=sum(council.tokens(u) for u in messages.values())
                            update(job['session_budget'],'record',key=str(root/'native-usage.json'),tokens=total,breakdown=stream_usage(messages))
                            council.dump(root/'native-usage.json',dict(model=job['literature_model'],messages=len(messages),tokens=total,token_breakdown=stream_usage(messages),accounting_version=2,accounting_source='per_invocation_stream',usage=messages))
                        for b in msg.get('content',[]) if isinstance(msg.get('content'),list) else []:
                            if b.get('type')=='tool_use' and b.get('name')=='mcp__codex__finish':finish_ids.add(b['id'])
                            if b.get('type')=='tool_result' and b.get('tool_use_id') in finish_ids and not b.get('is_error'):
                                saved=work/'native-completion.json'
                                if saved.is_file():
                                    done=council.read_json(saved);host_finished=done.get('job_id')==job['id'] and done.get('auto_session_id')==job['auto_session_id']
                            if b.get('type')=='tool_use' and b.get('name')=='Skill':
                                skill=b.get('input',{}).get('skill','');requested[b['id']]=skill
                                phase={'idea-discovery':'native-discovery','experiment-bridge':'native-implementation','auto-review-loop':'native-review'}.get(skill.split(':')[-1],'native-pipeline')
                                progress.emit(phase,'메인 자율 연구가 '+skill.split(':')[-1]+' 단계를 수행합니다.')
                            if b.get('type')=='tool_result' and not b.get('is_error') and '<tool_use_error>' not in str(b.get('content')):succeeded.add(b.get('tool_use_id'))
                        if row.get('type')=='result':results.append(row)
                if host_finished:break
                eventfile=work/'host-progress.json'
                if eventfile.exists():
                    event=council.read_json(eventfile)
                    if event!=last_event:progress.emit(event['phase'],event['message']);last_event=event
                # Live user stop/pause and resource changes do not wait for another model tool call.
                with TreeStore(job['db'])._connect() as conn:
                    session=conn.execute('SELECT status FROM automatic_sessions WHERE id=?',(job['auto_session_id'],)).fetchone()
                if not session or session['status']!='running':raise InterruptedError('프로젝트가 일시정지 또는 중지되었습니다. 원본 세션을 보존했습니다.')
            if host_finished and p.poll() is None:os.killpg(p.pid,signal.SIGTERM)
            try:p.wait(timeout=5)
            except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.wait(timeout=3)
            if host_finished:council.dump(root/'native-usage.json',dict(model=job['literature_model'],messages=len(messages),tokens=sum(council.tokens(u) for u in messages.values()),usage=messages,source='stream_until_validated_host_finish',closing_response_not_required=True))
            if results:
                result=results[-1];breakdown,accounting_source=calculate(stream_usage(messages),result.get('modelUsage'),usage_baseline)
                observed=usage_total(breakdown)
                update(job['session_budget'],'record',key=str(root/'native-usage.json'),tokens=observed,breakdown=breakdown)
                council.dump(root/'native-usage.json',dict(model=job['literature_model'],messages=len(messages),tokens=observed,token_breakdown=breakdown,accounting_source=accounting_source,accounting_version=2,usage=messages,model_usage=result.get('modelUsage'),provider_usage=result.get('usage'),total_cost_usd=result.get('total_cost_usd')))
            current_skills={requested[i].split(':')[-1] for i in requested.keys() & succeeded}
            skills,sources,_=session_skill_receipts(job)
            council.dump(root/'native-skill-receipts.json',dict(invoked=sorted(skills),current_invoked=sorted(current_skills),source_jobs=sources,requested=requested,succeeded=sorted(succeeded)))
            if not host_finished and (p.returncode or not results or results[-1].get('is_error') or results[-1].get('subtype')!='success'):raise RuntimeError('공식 연구 세션이 완료되지 않았습니다. 원본 세션·오류·사용량을 보존했습니다.')
            required={'research-lit','idea-discovery','novelty-check'} if job.get('task_role')=='discovery' else set(SKILLS)
            completion_path=work/'native-completion.json'
            if completion_path.is_file() and council.read_json(completion_path).get('job_id')==job['id'] and council.read_json(completion_path).get('outcome')=='rejected':
                from study_outcomes import REJECTION_SKILLS
                required=REJECTION_SKILLS
            if job.get('research_style')=='scout' and job.get('task_role')!='discovery':
                required.add('research-lit')
                receipt_path=work/'native-completion.json'
                if receipt_path.is_file() and not council.read_json(receipt_path).get('run_ids'):required={'research-pipeline','research-lit','idea-discovery'}
            if not required<=skills:raise RuntimeError('공식 파이프라인과 하위 Skills의 실제 성공 호출 기록이 불완전합니다.')
            for name,digest in council.read_json(plugin/'source-manifest.json').items():
                if hashlib.sha256((plugin/name).read_bytes()).hexdigest()!=digest:raise RuntimeError('공식 Skill 원본이 변경되어 완료로 처리하지 않습니다.')
            receipt=work/'native-completion.json'
            if not receipt.is_file():raise RuntimeError('실제 실행·Reviewer·Council·최종 보고 영수증이 없습니다.')
            completed=council.read_json(receipt)
            if completed.get('job_id')!=job['id'] or completed.get('auto_session_id')!=job['auto_session_id']:raise RuntimeError('이전 실행의 완료 기록을 현재 연구의 완료로 재사용하지 않습니다.')
            council.dump(root/'native-completion.json',completed)
            progress.emit('native-completed','넓은 탐색을 마치고 가설별 공식 연구 작업을 선정했습니다.' if job.get('task_role')=='discovery' else '독립 검토에 따른 실험 전 기각을 기록했습니다.' if completed.get('outcome')=='rejected' else '자율 연구와 Reviewer 검토·실험 결과 보고를 완료했습니다.',state='completed')
        finally:
            if p.poll() is None:
                os.killpg(p.pid,signal.SIGTERM)
                try:p.wait(timeout=8)
                except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.wait(timeout=3)
            with council.PROCESS_LOCK:council.ACTIVE_PROCESSES.discard(p)


class Host:
    def __init__(self,job):
        self.job=job;self.work=workspace(job);self.root=Path(job['run_dir']);self.store=TreeStore(job['db'])
        self.cfg={**council.DEFAULTS,**council.MODES[job['mode']],**job['council_overrides'],'project_session':job['project_session']}
        self.cfg['session_budget']=job['session_budget'];self.last_delivered_revision=-1;self.latest_context=None
    def event(self,phase,message):council.dump(self.work/'host-progress.json',dict(phase=phase,message=message,at=now()))
    def path(self,name):
        p=self.work/name
        if p.is_symlink() or not p.resolve().is_relative_to(self.work) or '.aris-official' in p.parts:raise ValueError('프로젝트 작업공간의 파일만 사용할 수 있습니다.')
        return p.resolve()
    def api(self,action,**args):
        from terminal import Client
        client=Client(self.job['native_api'],self.job['db']);client.health()
        return client.request('/api/native/action',dict(job_id=self.job['id'],action=action,**args))
    def require_skill(self,name):
        invoked,_,_=session_skill_receipts(self.job)
        if name not in invoked:raise ValueError('먼저 Skill 도구로 aris-official:'+name+'을 실제 호출하고 원래 절차를 따르세요. 문서 읽기만으로 단계를 대체하지 않습니다.')

    def execute(self,name,args):
        from session_budget import update
        if name not in {'context','receipt','scout_triage','finish'}:update(self.job['session_budget'],'check')
        context=self.api('context');self.latest_context=context
        if name=='context':return context
        if name=='exploration_council':
            self.require_skill('idea-discovery');self.require_skill('research-lit')
            from exploration import run
            self.event('verification','탐색 준비 · 논문 존재 검증 후 6개 관점 탐색을 시작합니다.')
            return run(self.job,self.root,self.work,self.cfg)
        if name=='paper_search':
            self.require_skill('research-lit')
            from scout import search
            self.event('scout-search','관심 분야와 연결할 논문을 실제 출처에서 조회합니다.')
            result=search(self.job,self.work,args)
            receipts=self.work/'scout-source-receipts.json';old=council.read_json(receipts) if receipts.exists() else []
            council.dump(receipts,old+[dict(session_id=self.job['auto_session_id'],native_cycle=self.job.get('native_cycle',0),source_receipt=result['source_receipt'])])
            return result
        if name=='novelty_check':
            self.require_skill('novelty-check')
            if len(set(args.get('queries',[])))<3:raise ValueError('서로 다른 기술적 검색어를 3개 이상 지정하세요.')
            import novelty
            idea=dict(hypothesis=args['hypothesis'],title=args['hypothesis'],novelty_queries=args.get('queries',[]))
            folder=self.root/'native-novelty'/novelty.key(idea)
            self.event('novelty-search','관련 선행연구를 새로 검색하고 논문 존재와 기술적 중복을 재확인합니다.')
            checked=novelty.audit(idea,folder,self.job['aris_repo'],self.cfg)
            if checked['papers']:
                frozen=folder/'novelty-review-prompt.txt'
                prompt='Independent novelty review of the actual retrieved sources below. Return ONLY JSON: novelty_status(plausible_delta|overlap_found|unverified), closest_prior_work(array of verified fresh IDs), technical_delta(string), limitations(array), verdict(PROCEED|PROCEED WITH CAUTION|ABANDON). ABANDON requires a specific verified paper containing this result, not mere proximity. No-result searches or missing abstracts cannot prove novelty. Metadata confirms existence only. Do not run tools, experiments or change files. Idea: '+json.dumps(idea,ensure_ascii=False)+'\n'+novelty.review_context(checked)
                if frozen.exists():prompt=frozen.read_text()
                else:frozen.write_text(prompt)
                cfg={**self.cfg,'output_tokens':4000,'codex_model':None,'codex_effort':'xhigh'}
                review=council.codex_call(folder/'reviewer',prompt,cfg,council.Budget(cfg,folder/'budget.json'),self.job['aris_repo'])
                review=novelty.calibrated(review,checked)
            else:review=novelty.calibrated(dict(novelty_status='unverified',limitations=['논문 근거를 재확인하지 못했습니다.']),checked)
            council.dump(folder/'review.json',review)
            return dict(novelty_receipt=checked['receipt'],review=review,evidence=json.loads(novelty.review_context(checked)))
        if name=='scout_candidates':
            self.require_skill('idea-discovery')
            result=self.api('scout_candidates',candidate=args);council.dump(self.work/'scout-selection.json',result);return result
        if name=='scout_triage':return self.api('scout_triage')
        if name=='target':
            from lab_worker import environment
            from target_explorer import query
            class Progress:
                def emit(_,phase,message,**kw):self.event(phase,message)
            profile,assignment,inventory=environment(self.job,self.root,Progress())
            if not args:return inventory
            return query(profile,inventory.get('context_root') or '',args,self.root/'target-reads')
        if name=='helper':
            tool=args['name'];values=args.get('args',[])
            if tool not in HELPERS or not isinstance(values,list) or not all(isinstance(v,str) for v in values):raise ValueError('허용된 공식 기록·논문 도구만 사용할 수 있습니다.')
            # Helpers accept paths; only this workspace is writable. No arbitrary Python or shell.
            for value in values:
                if value.startswith('/') and not Path(value).resolve().is_relative_to(self.work):raise ValueError('도구 경로는 연구 작업공간 내부여야 합니다.')
                if '..' in Path(value).parts:raise ValueError('상위 폴더 경로는 허용되지 않습니다.')
            result=subprocess.run(council.python_command(Path(self.job['aris_repo'])/'tools'/tool)+values,cwd=self.work,capture_output=True,text=True,timeout=180)
            logs=self.root/'native-helpers'/str(time.time_ns());logs.mkdir(parents=True)
            (logs/'stdout.log').write_text(result.stdout);(logs/'stderr.log').write_text(result.stderr)
            council.dump(logs/'request.json',dict(helper=tool,args=values,returncode=result.returncode))
            return dict(returncode=result.returncode,stdout=result.stdout[-24000:],stderr=result.stderr[-8000:],raw_logs=str(logs))
        if name in {'codex','codex-reply'}:
            self.require_skill('auto-review-loop' if context['completed_runs'] else 'idea-discovery')
            folder=self.root/'native-reviewer'/str(time.time_ns())
            self.event('native-review','메인 연구의 기존 Reviewer가 독립적으로 검토합니다.')
            prompt=args.get('prompt','')+'\nReturn ONLY JSON with your full review in review, score, verdict, weaknesses, minimum_fixes. Read-only inspection of the native project workspace is allowed; never execute experiments, mutate files or access credentials. This is the normal ARIS Reviewer, separate from advisory Council. Native workspace: '+str(self.work)+'\nCurrent project context:\n'+json.dumps(context,ensure_ascii=False)
            if self.job.get('hypothesis_task_id') and not context['completed_runs']:prompt+='\nFor this pre-experiment review also include disposition (continue|reject), rejection_kind (duplicate|low_novelty|infeasible when rejecting), rationale (specific evidence-based reason), evidence_urls (array of actual compared primary-source URLs). A reject decision needs explicit grounds; unknown novelty or a low score alone is insufficient. Temporary authentication, dependency or tool errors are not scientific rejection. Paper URLs are mandatory for duplicate/low_novelty rejection.'
            cfg={**self.cfg,'output_tokens':6000,'codex_model':args.get('model'),'codex_effort':args.get('config',{}).get('model_reasoning_effort','xhigh')}
            result=council.codex_call(folder,prompt,cfg,council.Budget(cfg,folder/'budget.json'),self.job['aris_repo'])
            council.dump(self.work/'reviewer-latest.json',dict(receipt=str(folder/'usage.json'),run_ids=[r['id'] for r in context['completed_runs']],review=result,hypothesis_task_id=self.job.get('hypothesis_task_id'),native_cycle=self.job.get('native_cycle',0),direction_revision=context['revision']))
            self.store.add_note(self.job['node_id'],'analysis','독립 Reviewer 평가',json.dumps(result,ensure_ascii=False,indent=2)[:99000])
            return dict(review=result,receipt=str(folder/'usage.json'))
        if name=='council':
            stage=args['stage']
            if self.job.get('research_style')=='scout':
                if stage=='ideas':raise ValueError('탐색 후보는 가볍게 선별하고 기존 Reviewer를 유지하세요. 전체 Council은 측정된 유망 결과에 집중합니다.')
                if not any(r['promising'] for r in self.api('scout_triage')['evaluations']):raise ValueError('유망성 기준을 충족한 실제 측정 후보가 아직 없습니다. 전체 Council을 호출하지 않습니다.')
            self.require_skill('idea-discovery' if stage=='ideas' else 'auto-review-loop')
            if stage not in {'ideas','results'}:raise ValueError('Council stage must be ideas/results')
            if stage=='results' and not context['completed_runs']:raise ValueError('실제 실험 결과가 있어야 결과 Council을 엽니다.')
            from research_worker import verify
            source=self.work/'literature';source.mkdir(exist_ok=True)
            for file in ['LITERATURE.md','source-evidence.json','candidate_papers.json']:shutil.copy2(self.path(file),source/file)
            class Progress:
                def emit(_,phase,message,**kw):self.event(phase,message)
            fingerprint=hashlib.sha256(json.dumps(dict(runs=context['completed_runs'] if stage=='results' else [],revision=context['revision'],evidence=(source/'source-evidence.json').read_text(),literature=(source/'LITERATURE.md').read_text()),sort_keys=True).encode()).hexdigest()
            verification=self.root/('native-verification-'+stage+'-'+fingerprint[:12]);verification.mkdir(exist_ok=True)
            evidence=verify(self.job,verification,source,Progress())
            cfg={k:v for k,v in self.cfg.items() if k in council.DEFAULTS or k in council.MODES[self.job['mode']] or k=='session_budget'}
            if self.job.get('cost_profile')=='economy':cfg.update(peer_model='haiku',chairman_model='sonnet')
            cfg.update(rounds=1,max_councils=1,result_evidence_ids=[r['id'] for r in context['completed_runs']] if stage=='results' else []);council.dump(self.root/'native-result-evidence.json',context['completed_runs']);config=self.root/('native-council-'+stage+'.json');council.dump(config,cfg)
            advisory_context={k:context.get(k) for k in ['research_style','research_preferences','completed_runs','max_runs']}
            advisory_context['human_directions']=context.get('shared_project',{}).get('directions',[])
            topic=self.job['topic']+'\nADVISORY '+stage+' Council. ARIS remains main executor; retain its independent Reviewer. Review actual pilot receipts and suggest evidence-based improvements. Cite ONLY IDs in the supplied evidence pack; do not treat paper IDs mentioned in historical assistant reports as supplied evidence.\n'+json.dumps(advisory_context,ensure_ascii=False)
            folder,inputs,fingerprint=freeze_advisory(self.work,stage,source/'LITERATURE.md',evidence,topic,cfg)
            if (folder/'status.json').is_file() and council.read_json(folder/'status.json').get('status')=='completed':
                status=council.read_json(folder/'status.json')
                if status.get('history_import_pending') is not False:council.import_completed_history(self.store,folder,status)
                council.dump(self.work/('advice-'+stage+'.json'),dict(stage=stage,native_cycle=self.job.get('native_cycle',0),path=str(folder),fingerprint=fingerprint,run_ids=[r['id'] for r in context['completed_runs']]))
                report=(folder/'round-1/COUNCIL_REPORT.md').read_text();(self.root/('advisory-'+stage+'.md')).write_text(report)
                return dict(report=report,reused=True)
            self.event('native-council','아이디어 Council이 검토합니다.' if stage=='ideas' else '실제 결과에 대해 Council이 추가 의견을 냅니다.')
            council.run(SimpleNamespace(mode=self.job['mode'],config=str(config),topic=topic,node_id=self.job['node_id'],db=self.job['db'],literature=str(inputs/'LITERATURE.md'),evidence=str(inputs/'evidence.json'),output=str(folder),aris_repo=self.job['aris_repo'],resume=(folder/'config.json').is_file()),lambda phase,message:self.event('native-council',message))
            receipt=dict(stage=stage,native_cycle=self.job.get('native_cycle',0),path=str(folder),fingerprint=fingerprint,run_ids=[r['id'] for r in context['completed_runs']])
            council.dump(self.work/('advice-'+stage+'.json'),receipt)
            report=(folder/'round-1/COUNCIL_REPORT.md').read_text();(self.root/('advisory-'+stage+'.md')).write_text(report)
            self.store.add_note(self.job['node_id'],'analysis','아이디어 Council 의견' if stage=='ideas' else '결과 Council 의견',report[:99000])
            return dict(report=report,receipt=receipt)
        if name=='experiment':
            if self.job.get('task_role')=='discovery':raise ValueError('넓은 탐색에서는 가설만 선정합니다. 실험은 독립 공식 연구 작업에서 수행합니다.')
            if self.last_delivered_revision>=0 and context['revision']>self.last_delivered_revision:raise ValueError('새 사용자 지시가 있습니다. context를 읽고 실행 소스에 반영하세요.')
            self.require_skill('experiment-bridge')
            if self.job.get('research_style')!='scout' and not self.job.get('hypothesis_task_id') and (not (self.work/'advice-ideas.json').is_file() or council.read_json(self.work/'advice-ideas.json').get('native_cycle',0)!=self.job.get('native_cycle',0)):raise ValueError('먼저 아이디어 Council 의견을 받아야 합니다.')
            from lab_worker import check_code
            code=check_code(self.path(args.pop('source')).read_text())
            allocation=context['execution_budget'];cap=allocation['max_timeout_seconds']
            if cap<1:raise ValueError('프로젝트의 남은 실행 시간 예산이 없습니다.')
            requested=args.get('timeout_seconds')
            if requested is not None and (type(requested) is not int or requested<1):raise ValueError('실험 시간은 양의 정수로 지정하거나 자동 배분하도록 생략하세요.')
            if allocation['policy']=='fixed':
                if requested is not None and requested>cap:raise ValueError('고정된 실험 시간 한도를 넘었습니다. 코드를 맞추거나 사용자가 자동 배분을 선택하세요.')
                effective=requested or cap
            else:effective=min(cap,max(requested or 0,allocation['recommended_timeout_seconds']))
            args['timeout_seconds']=effective
            node_id=self.job['node_id']
            if self.job.get('research_style')=='scout':node_id=council.read_json(self.work/'scout-selection.json')['node_id']
            spec={**args,'node_id':node_id,'code':code}
            allocation={**allocation,'requested_seconds':requested,'granted_seconds':effective}
            self.event('runtime-allocation','남은 프로젝트 예산 안에서 실험 시간을 '+str(effective)+'초로 '+('자동 배분했습니다.' if allocation['policy']=='auto' else '설정했습니다.'))
            self.event('code-review','메인 연구 Reviewer가 실행할 코드 자체를 검토합니다.')
            folder=review_directory(self.root,spec,context['revision'],context['resource_signature']);folder.mkdir(parents=True,exist_ok=True)
            council.dump(folder/'runtime-allocation.json',allocation)
            frozen=folder/'review-prompt.txt'
            prompt='Review exact Python code before execution for correctness, leakage, metric integrity, dependencies and matching research design. Return ONLY JSON: verdict (pass/block), reasons (array). Never execute it. The host has allocated '+str(effective)+' seconds and enforces this timeout by terminating the process group on the target. This is the authoritative runtime limit. In auto policy, pilot_seconds is a scheduling hint, not a hard cap. Do not block solely because an internal time guard differs or is absent; no internal wall-clock guard is required for host enforcement. Check real code/data/metric correctness normally. If code uses an internal deadline, BRAINDANCE_TIMEOUT_SECONDS and BRAINDANCE_DEADLINE_UNIX are provided at execution.\n'+json.dumps(dict(code=code,execution_spec={k:v for k,v in spec.items() if k!='code'},runtime_allocation=allocation,context=context),ensure_ascii=False)
            if frozen.exists():prompt=frozen.read_text()
            else:frozen.write_text(prompt)
            cfg={**self.cfg,'output_tokens':4000,'codex_model':None,'codex_effort':'xhigh'}
            review=council.codex_call(folder,prompt,cfg,council.Budget(cfg,folder/'budget.json'),self.job['aris_repo'])
            if review.get('verdict')!='pass':return dict(state='review_blocked',review=review,runtime_allocation=allocation)
            return self.api('experiment',payload=spec,review_receipt=str(folder/'usage.json'),direction_revision=context['revision'])
        if name=='receipt':return self.api('receipt',run_id=args['run_id'])
        if name=='finish':
            if self.job.get('task_role')=='discovery':
                for skill in ['research-lit','idea-discovery','novelty-check']:self.require_skill(skill)
                return self.api('finish',node_ids=args.get('node_ids',[]),report=str(self.path(args['report'])))
            brief=self.work/'RESEARCH_BRIEF.json'
            if brief.is_file() and not brief.is_symlink():
                from research_reports import validate_brief
                raw=council.read_json(brief)
                if raw.get('native_cycle')!=self.job.get('native_cycle',0):raise ValueError('현재 연구 사이클의 RESEARCH_BRIEF.json을 작성하세요.')
                summary=validate_brief(raw);summary['native_cycle']=self.job.get('native_cycle',0)
                council.dump(self.root/'research-brief.json',summary)
            required=SKILLS
            if args.get('outcome')=='rejected':
                from study_outcomes import REJECTION_SKILLS
                required=REJECTION_SKILLS
            if self.job.get('research_style')=='scout':required=(*SKILLS,'research-lit') if context['completed_runs'] else ('research-pipeline','research-lit','idea-discovery')
            for skill in required:self.require_skill(skill)
            report=self.path(args['report']);text=report.read_text()
            if not text.strip():raise ValueError('최종 연구 보고가 비어 있습니다.')
            return self.api('finish',report=str(report),**{k:args[k] for k in ['outcome','rejection_kind','reason'] if k in args})
        raise ValueError('Unknown host tool')


def serve(jobfile):
    host=Host(council.read_json(jobfile))
    tools=[('exploration_council','Six independent broad-discovery agents using verified literature',{}),('novelty_check','Fresh multi-source prior-art retrieval, no-cache existence checks and independent Reviewer comparison',{'hypothesis':{'type':'string'},'queries':{'type':'array','items':{'type':'string'}}}),('paper_search','Retrieve real recent or cross-domain papers with project duplicate tracking',{'query':{'type':'string'},'source':{'type':'string','enum':['arxiv','openalex']},'kind':{'type':'string','enum':['recent','cross-domain']},'domain':{'type':'string'},'limit':{'type':'integer'}}),('scout_candidates','Connect retrieved canonical paper IDs to a project interest and small experiment',{'paper_ids':{'type':'array','items':{'type':'string'}},'interest':{'type':'string'},'mechanism':{'type':'string'},'hypothesis':{'type':'string'},'experiment':{'type':'string'},'novelty_receipt':{'type':'string'},'ratings':{'type':'object'},'rating_basis':{'type':'string'}}),('scout_triage','Evaluate actual baseline/candidate and seed receipts against project thresholds',{}),('context','Shared project conversation, directions, limits and resources',{}),('target','Read-only selected target inventory or source query',{'op':{'type':'string'},'path':{'type':'string'},'start':{'type':'integer'},'lines':{'type':'integer'}}),('helper','Execute an allowed unmodified upstream bookkeeping/paper helper',{'name':{'type':'string'},'args':{'type':'array','items':{'type':'string'}}}),('codex','Original ARIS independent Reviewer; preserve Skill model/effort overrides',{'prompt':{'type':'string'},'model':{'type':'string'},'config':{'type':'object'}}),('codex-reply','Continue original project Reviewer',{'prompt':{'type':'string'},'threadId':{'type':'string'}}),('council','Additional advisory Council at ideas/results boundary',{'stage':{'type':'string','enum':['ideas','results']}}),('experiment','Review and submit immutable Python experiment to selected project resources',{'source':{'type':'string'},'title':{'type':'string'},'interpreter':{'type':'string'},'cwd':{'type':'string'},'args':{'type':'array','items':{'type':'string'}},'timeout_seconds':{'type':'integer'},'metric':{'type':'string'},'direction':{'type':'string','enum':['maximize','minimize']}}),('receipt','Poll actual run metrics/logs',{'run_id':{'type':'string'}}),('finish','Persist native final report after real Reviewer, Council and experiments',{'report':{'type':'string'},'node_ids':{'type':'array','items':{'type':'string'}}})]
    for name,_,properties in tools:
        if name=='finish':properties.update(outcome={'type':'string','enum':['measured','rejected']},rejection_kind={'type':'string','enum':['duplicate','low_novelty','infeasible']},reason={'type':'string'})
    def stop(*_):
        with council.PROCESS_LOCK:
            for p in council.ACTIVE_PROCESSES:
                if p.poll() is None:
                    try:os.killpg(p.pid,signal.SIGTERM)
                    except ProcessLookupError:pass
        raise SystemExit(1)
    signal.signal(signal.SIGTERM,stop)
    for line in sys.stdin:
        try:
            request=json.loads(line);ident=request.get('id');method=request.get('method')
            if ident is None:continue
            if method=='initialize':result=dict(protocolVersion='2024-11-05',capabilities=dict(tools={}),serverInfo=dict(name='braindance-native-host',version='1.0'))
            elif method=='tools/list':result=dict(tools=[dict(name=n,description=d,inputSchema=dict(type='object',properties=p)) for n,d,p in tools])
            elif method=='tools/call':
                try:
                    with redirect_stdout(sys.stderr):value=host.execute(request['params']['name'],request['params'].get('arguments',{}))
                    result=dict(content=[dict(type='text',text=json.dumps(value,ensure_ascii=False))])
                except Exception as error:result=dict(isError=True,content=[dict(type='text',text=str(error))])
                context=host.latest_context
                if context and context['revision']!=host.last_delivered_revision:
                    result['content'].append(dict(type='text',text='Latest shared project directions: '+json.dumps(context['shared_project'],ensure_ascii=False)))
                    host.last_delivered_revision=context['revision']
            elif method=='ping':result={}
            else:raise ValueError('Unsupported MCP method')
            print(json.dumps(dict(jsonrpc='2.0',id=ident,result=result),ensure_ascii=False),flush=True)
        except Exception as error:print(json.dumps(dict(jsonrpc='2.0',id=request.get('id'),error=dict(code=-32603,message=str(error)))),flush=True)


if __name__=='__main__':
    if sys.argv[1]=='--native-host':serve(sys.argv[2])


def action(server,payload):
    """Fast host mutations only. Models/review/Council run in the worker process."""
    job=server.research.get(payload['job_id']);config=job['config']
    if config.get('task')!='native' or job['state'] not in {'queued','running'}:raise ValueError('활성 자율 연구 작업이 아닙니다.')
    session=server.autopilot.get(config['auto_session_id'])
    if session['project_id']!=job['project_id'] or session['status']!='running':raise ValueError('자동 연구가 일시정지 또는 중지되었습니다.')
    node=server.store.get_node(job['node_id']);profile,assignment=server.experiments._resources(node)
    from experiments import resource_signature
    if resource_signature(profile,assignment)!=session['config']['resource_signature']:raise ValueError('프로젝트 실행 환경이 바뀌었습니다.')
    work=workspace(config)
    with server.store._connect() as conn:
        rows=[dict(r) for r in conn.execute('SELECT r.*,e.spec FROM experiment_runs r JOIN experiments e ON r.experiment_id=e.id WHERE r.project_id=? ORDER BY r.queued_at',(job['project_id'],))]
    rows=[r for r in rows if json.loads(r['spec']).get('generation',{}).get('native_session_id')==session['id'] and json.loads(r['spec']).get('generation',{}).get('native_cycle',0)==config.get('native_cycle',0) and json.loads(r['spec']).get('generation',{}).get('hypothesis_task_id')==config.get('hypothesis_task_id')]
    from experiments import completed_run_count
    completed_count=completed_run_count(rows)
    def receipt(row):
        run=server.experiments.run_info(row['id'])
        return {k:run.get(k) for k in ['id','state','result','stdout_tail','stderr_tail','queued_at','finished_at']}
    if payload['action']=='scout_candidates':
        if config.get('research_style')!='scout' and config.get('task_role')!='discovery':raise ValueError('탐색 모드에서만 논문 연결을 등록할 수 있습니다.')
        from scout import candidate
        from novelty import calibrated
        args=payload['candidate'];proof=Path(args.get('novelty_receipt','')).resolve()
        if not proof.is_relative_to((Path(job['run_dir'])/'native-novelty').resolve()) or not proof.is_file():raise ValueError('먼저 현재 가설로 novelty_check를 실행하고 novelty_receipt를 첨부하세요.')
        checked=council.read_json(proof)
        if checked['idea']['hypothesis']!=args['hypothesis'] or not proof.with_name('review.json').is_file():raise ValueError('현재 가설의 신규성 재검색·리뷰 기록이 필요합니다.')
        chosen=candidate(server.store,job['project_id'],job['node_id'],session['id'],args,cycle=config.get('native_cycle',0))
        review=calibrated(council.read_json(proof.with_name('review.json')),checked)
        ratings=args.get('ratings',{})
        if config.get('task_role')=='discovery':
            if not isinstance(args.get('rating_basis'),str) or not args['rating_basis'].strip() or len(args['rating_basis'])>3000:raise ValueError('점수 판단의 근거와 불확실성을 간결하게 기록하세요.')
            for field in ['potential','novelty_provisional','feasibility','falsifiability']:
                if type(ratings.get(field)) is not int or not 0<=ratings[field]<=100:raise ValueError('유망도·참신도·실현 가능성·검증 가능성을 0–100으로 평가하세요.')
        server.store.update_node(chosen['node_id'],metadata=dict(research_ratings=ratings,rating_basis=args.get('rating_basis',''),novelty_recheck=review,novelty=dict(assessment=review['novelty_status'],closest_prior_work=review.get('closest_prior_work',[]),technical_delta=review.get('technical_delta',''),uncertainty=review['novelty_limitations'])))
        return {**chosen,'novelty_recheck':review}
    if payload['action']=='scout_triage':
        from scout import triage,settings
        return dict(evaluations=[triage(server.experiments.run_info(r['id']),settings(server.store,job['project_id'])) for r in rows if r['state'] not in {'queued','running'}])
    if payload['action']=='context':
        from scout import settings,runtime_budget
        from steering import prompt_context
        current=prompt_context(server.store,job['project_id'])
        with server.store._connect() as conn:time_budget=server.experiments._budget(job['project_id'],assignment['updated_at'],assignment['time_budget_minutes']*60,conn)
        continuous=session['config'].get('execution_policy')=='until_deadline'
        allocation=runtime_budget(settings(server.store,job['project_id']),config.get('scout_preferences',{}),time_budget['remaining_seconds'],None if continuous else session['config']['max_cycles']-completed_count,config.get('research_style','focused'),until_deadline=continuous,experiment_timeout_seconds=session['config'].get('experiment_timeout_seconds'))
        return dict(discovery_interest=server.autopilot.root(job['project_id'])['title'][:200],hypothesis_task_id=config.get('hypothesis_task_id'),task_role=config.get('task_role','single'),research_style=config.get('research_style','focused'),research_preferences=settings(server.store,job['project_id']),shared_project=current,revision=current['revision'],usage=server.autopilot.state(job['project_id'])['usage'],
                    execution_budget=allocation,execution_policy=session['config'].get('execution_policy','bounded'),deadline_epoch=session['config'].get('deadline_epoch'),native_cycle=config.get('native_cycle',0),resource_signature=resource_signature(profile,assignment),
                    target=dict(profile=profile['name'],kind=profile['kind'],device_ids=config.get('allocated_devices',assignment['device_ids']),time_budget_minutes=assignment['time_budget_minutes'],context_path=config['context_path']),
                    max_runs=session['config']['max_cycles'],runs_started=completed_count+sum(r['state'] in {'queued','running'} for r in rows),attempts_started=len(rows),completed_experiments=completed_count,completed_runs=[receipt(r) for r in rows if r['state'] not in {'queued','running'}])
    if payload['action']=='receipt':
        row=next((r for r in rows if r['id']==payload['run_id']),None)
        if not row:raise ValueError('이 프로젝트 자율 연구의 실행이 아닙니다.')
        return receipt(row)
    if payload['action']=='experiment':
        with server.autopilot.lock:
            with server.store._connect() as conn:
                rows=[dict(r) for r in conn.execute('SELECT r.*,e.spec FROM experiment_runs r JOIN experiments e ON r.experiment_id=e.id WHERE r.project_id=? ORDER BY r.queued_at',(job['project_id'],))]
            rows=[r for r in rows if json.loads(r['spec']).get('generation',{}).get('native_session_id')==session['id'] and json.loads(r['spec']).get('generation',{}).get('native_cycle',0)==config.get('native_cycle',0) and json.loads(r['spec']).get('generation',{}).get('hypothesis_task_id')==config.get('hypothesis_task_id')]
            if server.autopilot.get(session['id'])['status']!='running':raise ValueError('자동 연구가 실행 중이 아닙니다.')
            completed_count=completed_run_count(rows)
            continuous=session['config'].get('execution_policy')=='until_deadline'
            if not continuous and completed_count>=session['config']['max_cycles']:raise ValueError('설정한 정상 측정 횟수를 완료했습니다. 기존 결과를 분석·검토하고 최종 보고하세요.')
            if any(r['state'] in {'queued','running'} for r in rows):raise ValueError('진행 중인 실험 결과를 먼저 확인하세요.')
            import steering
            revision=steering.snapshot(server.store,job['project_id'])['revision']
            if payload.get('direction_revision')!=revision:raise ValueError('새 사용자 지시가 도착했습니다. context를 읽고 코드를 다시 검토하세요.')
            spec=payload['payload']
            if config.get('research_style')=='scout':
                from scout import settings
                prefs=settings(server.store,job['project_id']);selected=server.store.get_node(spec['node_id'])
                if selected['project_id']!=job['project_id'] or selected['metadata'].get('scout_session')!=session['id'] or selected['metadata'].get('scout_cycle',0)!=config.get('native_cycle',0):raise ValueError('조회 논문과 연결한 이 탐색 세션의 가설을 먼저 등록하세요.')
            elif spec['node_id']!=job['node_id']:raise ValueError('프로젝트 노드가 일치하지 않습니다.')
            from scout import settings,runtime_budget
            with server.store._connect() as conn:time_budget=server.experiments._budget(job['project_id'],assignment['updated_at'],assignment['time_budget_minutes']*60,conn)
            allocation=runtime_budget(settings(server.store,job['project_id']),config.get('scout_preferences',{}),time_budget['remaining_seconds'],None if continuous else session['config']['max_cycles']-completed_count,config.get('research_style','focused'),until_deadline=continuous,experiment_timeout_seconds=session['config'].get('experiment_timeout_seconds'))
            if type(spec.get('timeout_seconds')) is not int or not 1<=spec['timeout_seconds']<=allocation['max_timeout_seconds']:raise ValueError('실험 시간이 현재 남은 프로젝트 예산의 배분 한도를 넘었습니다. 새 context로 다시 준비하세요.')
            reviewroot=review_directory(job['run_dir'],spec,revision,resource_signature(profile,assignment))
            if Path(payload['review_receipt'])!=reviewroot/'usage.json' or not (reviewroot/'usage.json').is_file():raise ValueError('실행할 코드에 대한 실제 Reviewer 영수증이 없습니다.')
            if council.parse_object((reviewroot/'response.txt').read_text()).get('verdict')!='pass':raise ValueError('코드 검토가 통과하지 않았습니다.')
            generation=dict(hypothesis_task_id=config.get('hypothesis_task_id'),allocated_devices=config.get('allocated_devices'),job_id=job['id'],auto_session_id=session['id'],native_session_id=session['id'],native_cycle=config.get('native_cycle',0),direction_revision=revision,review_receipt=str(reviewroot/'usage.json'),automatic_analysis=False,runtime_allocation={**allocation,'granted_seconds':spec['timeout_seconds']})
            experiment=server.experiments.create(spec,provenance=generation)
            approval=server.experiments.approve(experiment['id'],experiment['digest'],True,authority='automatic:'+session['id'])
            run=server.experiments.enqueue(experiment['id'],approval['id'])
            server.autopilot.save(session,message='자율 연구가 선택한 실험을 실행합니다.',cycles=completed_count,attempts=len(rows)+1,run_id=run['id'])
            return dict(run_id=run['id'],state=run['state'],experiment_id=experiment['id'],digest=experiment['digest'])
    if payload['action']=='finish':
        if payload.get('outcome') not in {None,'measured','rejected'}:raise ValueError('연구 결과 유형을 확인하세요.')
        if payload.get('outcome')=='rejected':
            from study_outcomes import reject
            return reject(server,job,session,rows,payload)
        if config.get('task_role')=='discovery':
            from research_tasks import stage
            report=Path(payload['report'])
            if report.is_symlink() or not report.resolve().is_relative_to(work) or not report.is_file():raise ValueError('현재 탐색의 보고서가 필요합니다.')
            if not (Path(job['run_dir'])/'broad-exploration-receipt.json').is_file():raise ValueError('6개 탐색 에이전트의 실제 실행 기록이 필요합니다.')
            tasks=stage(server,job,session,payload.get('node_ids',[]))
            (Path(job['run_dir'])/'native-summary.md').write_text(report.read_text())
            done=dict(job_id=job['id'],auto_session_id=session['id'],task_ids=[t['id'] for t in tasks],run_ids=[],discovery_only=True,completed_at=now())
            council.dump(work/'native-completion.json',done)
            server.store.add_note(job['node_id'],'analysis','넓은 탐색 · 가설별 연구 선정',report.read_text()[:99000])
            return done
        if config.get('research_style')=='scout':
            from scout import finish
            return finish(server,job,session,rows,payload['report'])
        if not rows or any(r['state'] in {'queued','running'} for r in rows):raise ValueError('실제 실험 완료 후 보고할 수 있습니다.')
        if not any(r['state']=='succeeded' and json.loads(r['result']).get('analysis',{}).get('status') in {'measured','compared'} for r in rows):raise ValueError('측정된 실험 결과 없이 완료로 표시하지 않습니다. 실패 원인과 남은 항목을 보존하세요.')
        require_council=not config.get('hypothesis_task_id')
        if config.get('hypothesis_task_id'):
            from scout import triage,settings
            require_council=any(triage(server.experiments.run_info(r['id']),settings(server.store,job['project_id']))['promising'] for r in rows)
        if require_council:
            advice=council.read_json(work/'advice-results.json')
            if set(advice['run_ids'])!={r['id'] for r in rows}:raise ValueError('최신 실험 결과의 Council 평가가 필요합니다.')
        if not config.get('hypothesis_task_id') and (not (work/'advice-ideas.json').is_file() or council.read_json(work/'advice-ideas.json').get('native_cycle',0)!=config.get('native_cycle',0)):raise ValueError('아이디어 Council의 실제 기록이 없습니다.')
        if not (work/'reviewer-latest.json').is_file():raise ValueError('기존 Reviewer의 결과 검토 기록이 없습니다. codex 도구로 결과를 검토하세요. 완료된 Council은 반복할 필요가 없습니다.')
        reviewer=council.read_json(work/'reviewer-latest.json')
        if set(reviewer['run_ids'])!={r['id'] for r in rows} or not Path(reviewer['receipt']).is_file():raise ValueError('최신 실험 결과에 대한 기존 Reviewer 기록이 필요합니다.')
        path=Path(payload['report'])
        if not path.resolve().is_relative_to(work) or path.is_symlink():raise ValueError('연구 작업공간의 최종 보고만 저장할 수 있습니다.')
        text=path.read_text()
        archive=Path(job['run_dir'])/'native-summary.md';archive.write_text(text)
        server.store.add_note(job['node_id'],'analysis','자율 연구 최종 보고',text[:99000])
        record=dict(job_id=job['id'],auto_session_id=session['id'],run_ids=[r['id'] for r in rows],report=str(archive),report_sha256=hashlib.sha256(text.encode()).hexdigest(),completed_at=now())
        council.dump(work/'native-completion.json',record)
        retain_brief(server,job)
        return record
    raise ValueError('지원하지 않는 자율 연구 작업입니다.')


def retain_brief(server,job):
    path=Path(job['run_dir'])/'research-brief.json'
    if path.is_file():
        server.store.add_note(job['node_id'],'analysis','연구 보고 요약',path.read_text())
