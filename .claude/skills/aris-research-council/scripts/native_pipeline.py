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
from stream_records import message as stream_message,blocks as stream_blocks
import shlex
from tree_store import TreeStore,now

SKILLS=('research-pipeline','idea-discovery','idea-creator','research-lit','research-review','research-refine-pipeline','experiment-bridge','auto-review-loop','novelty-check')
DISCOVERY_SKILLS={'research-lit','idea-discovery','idea-creator','novelty-check','research-review','research-refine-pipeline'}
HELPERS={'run_state.py','iteration_log.py','arxiv_fetch.py','verify_papers.py','provenance.py','evidence_check.py','review_gate.py','reviewer_route.py','idea_discovery_gate.py','forensics_gate.py','save_trace.sh','research_wiki.py','deepxiv_fetch.py','semantic_scholar_fetch.py','openalex_fetch.py','exa_search.py'}


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
    # Run the official installer, including its separately managed leaf agent.
    installer=repo/'tools/install_aris.sh'
    if not installer.is_file() or not (repo/'agents/aris-fanout-leaf.md').is_file():raise FileNotFoundError('원본 ARIS 설치 도구와 fan-out leaf agent가 필요합니다.')
    result=subprocess.run(['/bin/bash',str(installer),str(work),'--aris-repo',str(repo),'--all','--add-new','--quiet','--no-doc','--platform','claude'],capture_output=True,text=True,timeout=90)
    (work/'official-install.stdout.log').write_text(result.stdout);(work/'official-install.stderr.log').write_text(result.stderr)
    if result.returncode:raise RuntimeError('원본 ARIS 설치 실패: '+result.stderr[-1000:])
    manifest={str(p.relative_to(repo)):hashlib.sha256(p.read_bytes()).hexdigest() for part in ['skills','tools','agents','.claude-plugin'] for p in (repo/part).rglob('*') if p.is_file() and not p.is_symlink() and '__pycache__' not in p.parts}
    receipt=plugin/'source-manifest.json'
    if receipt.exists() and council.read_json(receipt)!=manifest:
        if any(name.startswith('agents/') for name in council.read_json(receipt)):raise ValueError('실행 중 원본 Skills 또는 agent가 변경되었습니다. 기존 작업을 보존하세요.')
        archive=work/('.aris-official-before-'+str(time.time_ns()));plugin.rename(archive);plugin.mkdir()
        for name in ['native-session.json']:
            if (work/name).exists():shutil.move(str(work/name),str(archive/name))
    if not (plugin/'source-manifest.json').exists():
        for part in ['skills','tools','agents','.claude-plugin']:shutil.copytree(repo/part,plugin/part,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        council.dump(plugin/'source-manifest.json',manifest)
    return work,plugin


def command(flag,*args):
    return [sys.executable,flag,*map(str,args)] if getattr(sys,'frozen',False) else [sys.executable,str(Path(__file__).resolve()),flag,*map(str,args)]


CONTRACT='''You are the main autonomous BrainDance research executor. Invoke Skill research-pipeline; follow its real idea-discovery -> experiment-bridge -> auto-review-loop -> summary workflow. AUTO_PROCEED=true, HUMAN_CHECKPOINT=false, AUTO_WRITE=false, COMPACT=true. ARIS owns implementation, debugging, interpretation and next-experiment decisions; do not replace its loop with a different staged planner. Load its actual nested Skills with the Skill tool at their boundaries. Existing measured results and completed stage artifacts remain reusable: loading a missing Skill is not permission to discard them or rerun a completed experiment. Use the installed ORIGINAL aris-fanout-leaf with Agent as specified by idea-creator Phase 1.5. Preserve its frozen lens list, coverage receipt and Codex brainstorm/jury slots. Do not substitute the separate exploration_council implementation for this original workflow.
Keep the normal ARIS Reviewer: call mcp__codex__codex for its independent novelty/code/result reviews, then implement its feedback and re-review per the original Skill. Council is ADDITIONAL ADVICE, not the Reviewer or its stop/quality gate. Call mcp__codex__council(stage=ideas) after literature/idea discovery and before the first experiment; call stage=results after measured results, before the next experiment and final summary. Council advice can be challenged with evidence; retain disagreement. Do not repeat an identical reviewer question just to fill a stage.
HOST TOOL ADAPTATION ONLY: Agent is available and the ORIGINAL leaf is installed by the official installer. Bash is available for local bookkeeping and original helpers; a host hook routes canonical helper calls unchanged and keeps GPU/SSH execution in the existing broker. Use mcp__codex__helper(name, args) to run the installed ORIGINAL upstream helpers, including review_gate.py, reviewer_route.py, idea_discovery_gate.py, forensics_gate.py, run_state.py and save_trace.sh; mcp__codex__target for read-only existing target inventory/source reads. Read/Write/Edit operate on this dedicated local project workspace. For all pilots, sanity checks, real experiments, retries and ablations use mcp__codex__experiment. It applies the already selected local/SSH device UUID, current direction, code review, run count and cumulative runtime budget. Never execute model code through a helper or call an external shell. No package installation, GPU reassignment or budget changes. Missing prerequisites should be investigated through target reads and repaired in experiment source where possible; do not invent interfaces or results.
Write a self-contained Python source file defining self_test() with real assertions and run_experiment(); omit __main__ (host appends it). Use the observed Python interpreter, existing project/data paths, BRAINDANCE_DEVICE/CUDA_VISIBLE_DEVICES, BRAINDANCE_METRICS_PATH and BRAINDANCE_ARTIFACT_DIR. Metrics JSON: baseline/candidate objects with the exact metric key. Experiment source can import the existing target repository. The experiment tool itself performs the original Reviewer code-review check; do not ask an identical extra code-review question before submitting the same source. The tool returns a real queued run; poll with mcp__codex__receipt and use its exit state/metrics/logs to debug and continue yourself. A rejected code review or failed execution is feedback to fix and resubmit, not a forced whole-project stop. Diagnose missing modules by checking existing observed Python environments before changing the experiment. Failed attempts do not consume the measured-experiment quota; they still consume actual runtime and model usage. Continue debugging within existing limits without asking the human for each repair. Negative but correctly measured results are valid completed experiments; never keep retrying just to obtain a positive scientific result.
For native crashes (e.g. SIGABRT), inspect the retained fatal-signal stack and failing operation before changing scientific conditions. If repeated simulator/renderer initialization is implicated, consider bounded foreground child processes in the same supervised process group. Preserve the specified seeds, initial states, controls and measurements; save per-trial data atomically and retain child logs, return codes, unresolved IDs and actual termination reasons. Never silently omit crashed trials, rename an undefined metric into a successful result, or treat a passing self-test as a completed scientific experiment.
For the literature Council input, write LITERATURE.md plus source-evidence.json {papers:[{id,title,url,arxiv_id,doi,source_excerpt,evidence_level,verification_status}]} and candidate_papers.json array with matching ids. Only retrieved readable evidence; unknown ids=null. Council invokes the actual upstream verifier before admitting sources. Preserve source text, original traces and limitations.
Call mcp__codex__context at the start and before every new experiment to receive the SAME shared project conversation, latest human directions, remaining budget and selected target. Changes govern the next immutable experiment; experiments in flight keep their exact source. Pause/stop/resource changes are enforced by the host. All responses and reports in Korean, using BrainDance branding; internal Skill identifiers belong in technical traces. Original identifiers/quotations remain intact.
When the ORIGINAL auto-review-loop reaches its own stopping condition, write NARRATIVE_REPORT.md from actual receipts, record limitations, and call mcp__codex__finish(report='NARRATIVE_REPORT.md'). Do not declare completion without real execution, both Council advice stages, and real ARIS Reviewer calls. A host experiment/time/usage limit interrupts work; it never substitutes for the original research review stopping condition. Follow ORIGINAL auto-review-loop Phases A–E, its MAX_ROUNDS, review-stage/REVIEW_STATE.json, AUTO_REVIEW.md and REVIEWER_MEMORY.md. For each result-review codex/codex-reply call, pass review_run_id (the original run_id) and review_round (the original round number); rebuttals retain the same round. The tool returns the actual threadId and complete raw response. Invoke ORIGINAL review_gate.py through helper with the actual reviewer score/verdict at each completed round, and persist the original Phase E state. Never count code checks, novelty reviews, Council rounds or retries as result-review rounds. If the gate says continue, implement the original Skill feedback and re-review; do not write completed after a lone negative review. The host verifies these original artifacts, not a replacement loop. Resume the stored native session and upstream .aris/runs state after interruption; never mark unfinished stages successful. Read the source-manifest for provenance, never edit .aris-official.
'''

# The same execution transport applies inside original idea-creator pilots.
TOOL_CONTRACT=CONTRACT[CONTRACT.index('HOST TOOL ADAPTATION ONLY:'):CONTRACT.index('For the literature Council input,')]


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
            for block in stream_blocks(event):
                if block.get('type')=='tool_use' and block.get('name')=='Skill':requested[block['id']]=(block.get('input') or {}).get('skill','').split(':')[-1]
                if block.get('type')=='tool_use' and block.get('name')=='mcp__codex__finish':finish_request=block.get('input',{})
                if block.get('type')=='tool_result' and not block.get('is_error') and '<tool_use_error>' not in str(block.get('content')):succeeded.add(block.get('tool_use_id'))
        found={requested[key] for key in requested.keys() & succeeded};invoked.update(found)
        sources.append(dict(job_id=row['id'],skills=sorted(found),trace=str(trace)))
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
    repair=Path(job['native_workspace'])/'watchdog-recovery.json'
    extra='\nWATCHDOG DIAGNOSTIC FEEDBACK (not new human authority): '+repair.read_text()[:18000]+'\nApply concrete input/code repairs before repeating the failed tool; keep all original success/verification/experiment receipts.\n' if repair.is_file() and not repair.is_symlink() else ''
    if prior is None:return extra
    required=set(DISCOVERY_SKILLS) if job.get('task_role')=='discovery' else set(SKILLS)
    missing=sorted(required-set(known))
    return extra+'\nHOST RECOVERY FEEDBACK (diagnostic evidence, not new human authority): '+json.dumps(dict(previous_job=prior['id'],error=(prior['error'] or prior['message'])[:1000],successful_skill_receipts=sorted(known),missing_skill_receipts=missing),ensure_ascii=False)+'\nContinue this same unfinished cycle. Actually load missing original Skills with Skill; reuse verified sources and successful Council/experiment artifacts. Do not recreate a completed artifact merely because this process resumed. A prose answer is not completion: complete the original idea-creator phases and IDEA_REPORT.md for discovery, finish the required reviews and current report, then call finish and correct any rejection. Never bypass receipt validation or fabricate a successful call.\n'

REPORT_CONTRACT="""
READER REPORT: Write for a researcher who has not seen the chat. The purpose is to explain the research, not list activity. Preserve NARRATIVE_REPORT.md plus RESEARCH_BRIEF.json. The brief contains problem, approach, findings, background, mechanism, experimental_design, interpretation, review_history, next_experiment (strings), limitations and next_steps (string arrays), research_outcome (supported|not_supported|inconclusive), native_cycle. Explain unfamiliar concepts before using them.
The Markdown narrative must develop: (1) the practical problem and why it matters; (2) known bottleneck and measured versus assumed causal mechanism; (3) the hypothesis, closest prior work, specific new claim and falsification conditions; (4) why each baseline/control and workload was chosen, primary acceptance criteria, seeds/splits, measurement boundaries and unmeasured conditions; (5) actual results with effect sizes and uncertainty supported by retained per-trial data, followed by an explanation of what each result implies; (6) each ORIGINAL review round: criticism, resulting code/design changes, new measurement or explicitly unexecuted follow-up, and remaining objection; (7) exact deployed code/functions and reproduction path; (8) the strongest remaining alternative explanation and next decisive experiment. Use clear Korean paragraphs, focused tables and honest figures. Never invent an explanation or CI to make a report deeper.
A process exit of zero, passing self-test, improvement over a weak baseline, and a Reviewer ready/almost verdict are NOT scientific success. State explicitly whether the PRIMARY research goal was supported, not supported in the tested setting, or still untested. A negative pilot is useful evidence but not a positive method result. Do not cherry-pick a positive auxiliary metric or omit a no-change/strong baseline. Keep synthetic/proxy, offline/open-loop, actual target workload, and deployment hardware distinct.
Original review_gate.py and MAX_ROUNDS remain authoritative. Do not force four empty reviews or end after a negative review. If the original gate continues, address its substantive criticism and run the decisive follow-up when it needs new evidence; editing the report alone is insufficient for a claim that depends on unmeasured conditions. If time/allowance prevents the experiment, preserve it as pending or deferred and close only the bounded report scope the real Reviewer approved. The main project continues unresolved research while authorized. Finish requires actual original discovery/refinement artifacts and the actual upstream idea-discovery gate, not just a Skill invocation. Do not manufacture state or receipts.
References contain paper URLs ONLY. Full sources/traces stay local. No raw JSON dumps, bibliography metadata or repetitive activity logs in the reader report. The host retains source references, measured tables and figures. These reporting requirements and human instructions take precedence over the advisor response template; do not wait for human answers to routine critical-research questions.
"""


NOVELTY_CONTRACT="""
FRESH NOVELTY RECHECK: Invoke original novelty-check for each new mechanism before implementing. Re-search actual literature instead of re-reading the frozen initial pack. Use novelty_check(hypothesis, queries=[at least 3 distinct targeted searches]); the host searches both installed source clients without date filters, re-verifies paper existence with --no-cache, and obtains the original independent Reviewer novelty comparison. This tool supplies the original Skill's source/verification/reviewer slot; do not repeat an identical Reviewer call. Attach its novelty_receipt when registering scout_candidates. State closest prior work, concrete mechanism-level delta and coverage limits. Never equate an existing ID, a new combination of keywords, better measurements, or no search hits with proven novelty. If sources cannot be checked, say unverified; feasibility pilots may continue with that label. Council separately re-searches its actual generated proposals before anonymous review. Preserve all original receipts and errors.
"""


DISCOVERY_CONTRACT="""Run the ORIGINAL idea-discovery workflow, including its nested idea-creator Skill. Do not replace its Phase 0–6 with a custom six-agent planner. Phase 0 wiki loading is conditional exactly as upstream specifies; Phase 1 is real literature survey; Phase 1.5 uses the installed aris-fanout-leaf in upstream bounded waves; Phase 2 uses the original independent Codex brainstorm; preserve the original novelty checks, reviewer, pilots and idea-stage/IDEA_REPORT.md. The user's broad-exploration prompt is research direction, not a replacement workflow. Council is additional advice after original idea creation. The original Skill decides candidates; the host only retains their tree/task records. Register shortlisted hypotheses with scout_candidates and original evidence/ratings, then finish with node_ids. Original pilots may run through experiment after the idea-creator/run-experiment Skills and a registered candidate; no untracked GPU shell execution. If the broker is sequential, await each pilot before the next. Write LITERATURE.md/source-evidence.json/candidate_papers.json from the original survey for the host's existing source verifier, without redoing completed survey work. Preserve all original idea-stage artifacts and actual pilot receipts for the later per-hypothesis study.
"""

STUDY_CONTRACT="""
This is ONE independent preliminary study, not the broad discovery coordinator. Read HYPOTHESIS.json. Invoke the unmodified official research-pipeline for this selected problem/hypothesis, preserving its idea-discovery, experiment-bridge, original Reviewer, auto-review-loop, debugging and summary. Reuse supplied literature as a starting point, check it, refine the selected hypothesis without switching to unrelated topics. ARIS authors real experiment source itself. Report this study's observations, failures and limitations in its own NARRATIVE_REPORT.md and RESEARCH_BRIEF.json. Other tasks' results are shared context, never this task's measured receipts. Original ARIS Reviewer and its internal loops remain required. Exploratory advice, if supplied, is context rather than validation. If HYPOTHESIS.json marks human_requested, no broad-discovery receipt is implied: verify the requested hypothesis and prior art through the original pipeline before experiment implementation; the extra full Council is optional for ideas and negative preliminary results, required for a promising measured pilot before final reporting. Avoid repeating broad ideation inside this fixed study. The project host starts other hypotheses/new discovery after your completed study; do not force this one hypothesis to run until the global deadline or fabricate a positive outcome.
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
        contract=human+'\n'+DISCOVERY_CONTRACT+TOOL_CONTRACT+NOVELTY_CONTRACT+REPORT_CONTRACT
        if job.get('research_scope')=='ideation':contract+='\nIDEATION SCOPE: Run the ORIGINAL idea-discovery/idea-creator to identify actual problems and bottlenecks before selecting a solution. Prioritize observed code/trace evidence, literature gaps, causal alternatives and falsifiable problem definitions. Original small diagnostic pilots remain available where informative. Produce the original ranked report and refined plans; selected ideas stay recorded as recommendations. The host will NOT start full per-hypothesis implementation studies in this scope. Continue unresolved problem discovery until the authorized time or account-allowance stop; do not loop over unchanged completed papers.\n'
    elif job.get('hypothesis_task_id'):contract+=STUDY_CONTRACT
    if job.get('research_style')=='scout' and job.get('task_role')!='discovery':
        from scout import CONTRACT as scout_contract
        contract+='\n'+scout_contract
        council.dump(root/'scout-settings.json',job.get('scout_preferences',{}))
    from session_budget import time_only,deadline_for
    continuous=time_only(job)
    if continuous:
        contract+='\nTIME-ONLY CONTINUOUS RESEARCH: The human authorized research until the absolute deadline '+str(deadline_for(job))+'. There are NO project model-call, token, dollar or experiment-count caps. Usage is still recorded. A configured account quota_guard is a separate hard stop: never disable it, assume missing usage is safe, or override the start-minus-percentage-point threshold. context.max_runs=null means unlimited; do not stop because of previous numeric defaults. Follow the official pipeline and its artifact-driven internal review loop, not a timer-based fresh review. Finish each scientifically coherent cycle with its real reviewed report using finish; the host then continues the next exploration cycle automatically until the deadline. A successful or negative experiment is information, not permission to terminate the whole project. Explore the next unresolved hypothesis or a new cross-field connection; preserve failures and avoid repeating unchanged completed pilots. When the host says a new cycle starts, create a NEW upstream pipeline run in the SAME shared project conversation/workspace, reusing evidence and reviewer context appropriately.\n'
    (work/'CLAUDE.md').write_text(contract)
    statefile=work/'native-session.json';state=council.read_json(statefile) if statefile.exists() else {}
    from usage_accounting import prior_baseline,stream_usage,calculate,total as usage_total
    usage_baseline=prior_baseline(TreeStore(job['db']),job,state.get('session_id'))
    settings=work/'.host-settings.json'
    hook=command('--native-shell',str(root/'job.json'))
    council.dump(settings,dict(hooks=dict(PreToolUse=[dict(matcher='Bash',hooks=[dict(type='command',command=shlex.join(hook),timeout=30)])])))
    argv=['claude','-p','--verbose','--output-format','stream-json','--model',job['literature_model'],
          '--append-system-prompt',advisor_prompt(),'--setting-sources','project','--settings',str(settings),'--add-dir',str(Path(job['aris_repo']).resolve()),'--strict-mcp-config','--mcp-config',str(mcp),
          '--permission-mode','acceptEdits','--permission-prompts','none',
          '--tools','Skill,Read,Write,Edit,Glob,Grep,WebSearch,WebFetch,Agent,Bash,TaskOutput,TaskStop',
          '--allowedTools','Skill,Read,Write,Edit,Glob,Grep,WebSearch,WebFetch,Agent(aris-fanout-leaf),Bash,TaskOutput,TaskStop,mcp__codex__*']
    if job.get('project_session',{}).get('path'):argv+=['--add-dir',job['project_session']['path']]
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
                        if not isinstance(row,dict):continue
                        if row.get('session_id'):council.dump(statefile,dict(session_id=row['session_id'],updated_at=now()))
                        msg=stream_message(row)
                        if row.get('type')=='assistant' and msg.get('id'):
                            ident=msg['id']
                            if ident not in messages and len(messages)>=reserved:
                                update(job['session_budget'],'reserve',key=str(root/'native-usage.json'),calls=1,estimate=0);reserved+=1
                            messages[ident]=msg.get('usage',{})
                            total=sum(council.tokens(u) for u in messages.values())
                            update(job['session_budget'],'record',key=str(root/'native-usage.json'),tokens=total,breakdown=stream_usage(messages))
                            council.dump(root/'native-usage.json',dict(model=job['literature_model'],messages=len(messages),tokens=total,token_breakdown=stream_usage(messages),accounting_version=2,accounting_source='per_invocation_stream',usage=messages))
                        for b in stream_blocks(row):
                            if b.get('type')=='tool_use' and b.get('name')=='mcp__codex__finish':finish_ids.add(b['id'])
                            if b.get('type')=='tool_result' and b.get('tool_use_id') in finish_ids and not b.get('is_error'):
                                saved=work/'native-completion.json'
                                if saved.is_file():
                                    done=council.read_json(saved);host_finished=done.get('job_id')==job['id'] and done.get('auto_session_id')==job['auto_session_id']
                            if b.get('type')=='text' and b.get('text','').strip():
                                text=b['text'].strip()
                                progress.emit('native-narration',text[:1800])
                            if b.get('type')=='tool_use' and b.get('name') in {'Agent','WebSearch','Bash'}:
                                detail=b.get('input') or {};tool=b['name']
                                label=detail.get('description') or detail.get('query') or detail.get('command') or detail.get('subagent_type') or tool
                                progress.emit('native-agent' if tool=='Agent' else 'native-tool',tool+' · '+str(label)[:300])
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
            required=set(DISCOVERY_SKILLS) if job.get('task_role')=='discovery' else set(SKILLS)
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
        if name not in invoked:raise ValueError('먼저 Skill 도구로 '+name+'을 실제 호출하고 원래 절차를 따르세요. 문서 읽기만으로 단계를 대체하지 않습니다.')

    def execute(self,name,args):
        from session_budget import update
        if name not in {'context','receipt','scout_triage','finish'}:update(self.job['session_budget'],'check')
        context=self.api('context');self.latest_context=context
        if name=='context':return context
        if name=='exploration_council':
            raise ValueError('원본 idea-creator의 Phase 1.5 aris-fanout-leaf를 사용하세요. 별도 탐색기로 대체하지 않습니다.')
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
            from official_review import helper
            return helper(self.job,tool,values)
        if name in {'codex','codex-reply'}:
            self.require_skill('auto-review-loop' if args.get('review_run_id') else 'idea-discovery')
            result_scope=bool(args.get('review_run_id')) and any(r['state']=='succeeded' and r.get('result',{}).get('analysis',{}).get('status') in {'measured','compared'} for r in context['completed_runs']) and not context.get('active_runs')
            if result_scope:
                from official_review import validate_round
                validate_round(args)  # reject missing original run/round before spending a model call
            folder=self.root/'native-reviewer'/str(time.time_ns())
            self.event('native-review','메인 연구의 기존 Reviewer가 독립적으로 검토합니다.')
            prompt=args.get('prompt','')+'\nFollow the ORIGINAL Skill slot requested output format, preserving full brainstorm/review text and any Score/Verdict fields verbatim. Read-only inspection of the native project workspace is allowed; never execute experiments, mutate files or access credentials. This is the normal ARIS Reviewer, separate from advisory Council. Native workspace: '+str(self.work)+'\nCurrent project context:\n'+json.dumps(context,ensure_ascii=False)
            if result_scope:prompt+='\nAfter your normal review, append a fenced JSON object with research_assessment: {outcome: supported|not_supported|inconclusive, primary_goal: string, scope: string, criteria: [{criterion: string, status: pass|fail|unmeasured, run_ids: [actual measured IDs], reason: string}]}. This assesses the actual PRIMARY scientific goal, not report readiness. Auxiliary gains or improvement over a poor baseline do not establish the goal. Unmeasured deployment success/latency stays unmeasured. Keep your original review text and gate unchanged.\nInclude exactly one anchored Score: X/10 field and exactly one Verdict: ready / almost / not ready field in your full review, for the ORIGINAL gate parser. Do not repeat these fields.'
            if self.job.get('hypothesis_task_id') and not context['completed_runs']:prompt+='\nFor this pre-experiment review also include disposition (continue|reject), rejection_kind (duplicate|low_novelty|infeasible when rejecting), rationale (specific evidence-based reason), evidence_urls (array of actual compared primary-source URLs). A reject decision needs explicit grounds; unknown novelty or a low score alone is insufficient. Temporary authentication, dependency or tool errors are not scientific rejection. Paper URLs are mandatory for duplicate/low_novelty rejection.'
            cfg={**self.cfg,'output_tokens':6000,'codex_model':args.get('model'),'codex_effort':args.get('config',{}).get('model_reasoning_effort','xhigh'),'_native_text':True,'project_session':None,'_project_cwd':str(self.work),'_resume_thread':args.get('threadId') if name=='codex-reply' else None}
            result=council.codex_call(folder,prompt,cfg,council.Budget(cfg,folder/'budget.json'),self.job['aris_repo'])
            if isinstance(result,dict) and 'text' in result:
                from official_review import assessment
                result=assessment(self.job,result['text'],required=result_scope)
            if result_scope:
                from official_review import record_review
                record_review(self.job,args,context,folder,result)
            council.dump(self.work/'reviewer-latest.json',dict(receipt=str(folder/'usage.json'),run_ids=[r['id'] for r in context['completed_runs']],review=result,hypothesis_task_id=self.job.get('hypothesis_task_id'),native_cycle=self.job.get('native_cycle',0),direction_revision=context['revision']))
            self.store.add_note(self.job['node_id'],'analysis','독립 Reviewer 평가',json.dumps(result,ensure_ascii=False,indent=2)[:99000])
            usage=council.read_json(folder/'usage.json')
            raw=self.work/'review-stage/raw'/folder.name;raw.mkdir(parents=True,exist_ok=True)
            shutil.copy2(folder/'response.txt',raw/'response.txt')
            (raw/'prompt.txt').write_text(prompt)
            return dict(review=result,receipt=str(folder/'usage.json'),threadId=usage.get('thread_id'),model=usage.get('model'),raw_response=str(raw/'response.txt'),raw_prompt=str(raw/'prompt.txt'))
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
            if self.job.get('task_role')=='discovery':self.require_skill('idea-creator')
            elif self.job.get('hypothesis_task_id'):
                self.require_skill('research-refine-pipeline')
                from official_workflow import plans
                plans(self.job)
            if self.last_delivered_revision>=0 and context['revision']>self.last_delivered_revision:raise ValueError('새 사용자 지시가 있습니다. context를 읽고 실행 소스에 반영하세요.')
            self.require_skill('run-experiment' if self.job.get('task_role')=='discovery' else 'experiment-bridge')
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
                brief=self.work/'RESEARCH_BRIEF.json'
                value=council.read_json(brief) if brief.is_file() else {}
                absent=[k for k in ['problem','approach','findings','background','mechanism','experimental_design','interpretation','review_history','next_experiment','research_outcome'] if not value.get(k)]
                if absent:raise ValueError('아이디에이션 보고서가 문제·근거·남은 검증을 설명해야 합니다. RESEARCH_BRIEF.json 보완: '+', '.join(absent))
                from research_reports import validate_brief
                summary=validate_brief(value);summary['native_cycle']=self.job.get('native_cycle',0)
                council.dump(self.root/'research-brief.json',summary)
                from official_workflow import completed
                completed(self.job)
                for skill in DISCOVERY_SKILLS:self.require_skill(skill)
                return self.api('finish',node_ids=args.get('node_ids',[]),report=str(self.path(args['report'])))
            brief=self.work/'RESEARCH_BRIEF.json'
            if brief.is_file() and not brief.is_symlink():
                from research_reports import validate_brief
                raw=council.read_json(brief)
                if raw.get('native_cycle')!=self.job.get('native_cycle',0):raise ValueError('현재 연구 사이클의 RESEARCH_BRIEF.json을 작성하세요.')
                summary=validate_brief(raw);summary['native_cycle']=self.job.get('native_cycle',0)
                council.dump(self.root/'research-brief.json',summary)
            required=SKILLS
            if args.get('outcome')!='rejected':
                from official_workflow import completed
                completed(self.job)
                value=council.read_json(brief) if brief.is_file() else {}
                absent=[k for k in ['background','mechanism','experimental_design','interpretation','review_history','next_experiment','research_outcome'] if not value.get(k)]
                if absent:raise ValueError('독자가 연구를 이해하도록 보고서 설명을 보완하세요: '+', '.join(absent))
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
    tools=[('novelty_check','Fresh multi-source prior-art retrieval, no-cache existence checks and independent Reviewer comparison',{'hypothesis':{'type':'string'},'queries':{'type':'array','items':{'type':'string'}}}),('paper_search','Retrieve real recent or cross-domain papers with project duplicate tracking',{'query':{'type':'string'},'source':{'type':'string','enum':['arxiv','openalex']},'kind':{'type':'string','enum':['recent','cross-domain']},'domain':{'type':'string'},'limit':{'type':'integer'}}),('scout_candidates','Connect retrieved canonical paper IDs to a project interest and small experiment',{'paper_ids':{'type':'array','items':{'type':'string'}},'interest':{'type':'string'},'mechanism':{'type':'string'},'hypothesis':{'type':'string'},'experiment':{'type':'string'},'novelty_receipt':{'type':'string'},'ratings':{'type':'object'},'rating_basis':{'type':'string'}}),('scout_triage','Evaluate actual baseline/candidate and seed receipts against project thresholds',{}),('context','Shared project conversation, directions, limits and resources',{}),('target','Read-only selected target inventory or source query',{'op':{'type':'string'},'path':{'type':'string'},'start':{'type':'integer'},'lines':{'type':'integer'}}),('helper','Execute installed original ARIS helpers, including review_gate.py and save_trace.sh; no replacement policy',{'name':{'type':'string'},'args':{'type':'array','items':{'type':'string'}}}),('codex','Original ARIS independent Reviewer; preserve Skill model/effort overrides',{'prompt':{'type':'string'},'model':{'type':'string'},'config':{'type':'object'},'review_run_id':{'type':'string'},'review_round':{'type':'integer'}}),('codex-reply','Continue original project Reviewer',{'prompt':{'type':'string'},'threadId':{'type':'string'},'review_run_id':{'type':'string'},'review_round':{'type':'integer'}}),('council','Additional advisory Council at ideas/results boundary',{'stage':{'type':'string','enum':['ideas','results']}}),('experiment','Review and submit immutable Python experiment to selected project resources',{'source':{'type':'string'},'title':{'type':'string'},'interpreter':{'type':'string'},'cwd':{'type':'string'},'args':{'type':'array','items':{'type':'string'}},'timeout_seconds':{'type':'integer'},'metric':{'type':'string'},'direction':{'type':'string','enum':['maximize','minimize']}}),('receipt','Poll actual run metrics/logs',{'run_id':{'type':'string'}}),('finish','Persist native final report after real Reviewer, Council and experiments',{'report':{'type':'string'},'node_ids':{'type':'array','items':{'type':'string'}}})]
    for name,_,properties in tools:
        if name=='target':
            properties.clear()
            properties.update(op={'type':'string','enum':['inventory','discover','read','search','stat','python']},
                files={'type':'array','items':{'type':'object','properties':{'path':{'type':'string'},'start_line':{'type':'integer'},'lines':{'type':'integer'}},'required':['path']}},
                terms={'type':'array','items':{'type':'string'}},paths={'type':'array','items':{'type':'string'}},
                hints={'type':'array','items':{'type':'string'}},path={'type':'string'})
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
    elif sys.argv[1]=='--native-shell':
        from native_shell import main
        main(sys.argv[2])
    elif sys.argv[1]=='--native-helper':
        result=Host(council.read_json(sys.argv[2])).execute('helper',council.read_json(sys.argv[3]))
        print(result['stdout'],end='');print(result['stderr'],end='',file=sys.stderr)
        raise SystemExit(result['returncode'])


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
                    quota_guard=session['config'].get('quota_guard'),account_usage=session['progress'].get('account_usage'),
                    execution_budget=allocation,execution_policy=session['config'].get('execution_policy','bounded'),deadline_epoch=session['config'].get('deadline_epoch'),native_cycle=config.get('native_cycle',0),resource_signature=resource_signature(profile,assignment),
                    target=dict(profile=profile['name'],kind=profile['kind'],device_ids=config.get('allocated_devices',assignment['device_ids']),time_budget_minutes=assignment['time_budget_minutes'],context_path=config['context_path']),
                    max_runs=session['config']['max_cycles'],active_runs=[r['id'] for r in rows if r['state'] in {'queued','running'}],runs_started=completed_count+sum(r['state'] in {'queued','running'} for r in rows),attempts_started=len(rows),completed_experiments=completed_count,completed_runs=[receipt(r) for r in rows if r['state'] not in {'queued','running'}])
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
            from official_ideas import validate
            validate(config)
            recommended=payload.get('node_ids',[])
            if config.get('research_scope')=='ideation':
                if not isinstance(recommended,list) or len(recommended)>5:raise ValueError('추천 가설 목록을 확인하세요.')
                for ident in recommended:
                    node=server.store.get_node(ident)
                    if node['project_id']!=job['project_id'] or node['kind']!='hypothesis':raise ValueError('같은 프로젝트의 가설만 추천하세요.')
            tasks=stage(server,job,session,[] if config.get('research_scope')=='ideation' else recommended)
            (Path(job['run_dir'])/'native-summary.md').write_text(report.read_text())
            done=dict(job_id=job['id'],auto_session_id=session['id'],task_ids=[t['id'] for t in tasks],recommended_node_ids=recommended,run_ids=[r['id'] for r in rows],discovery_only=True,completed_at=now())
            council.dump(work/'native-completion.json',done)
            server.store.add_note(job['node_id'],'analysis','넓은 탐색 · 가설별 연구 선정',report.read_text()[:99000])
            retain_brief(server,job)
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
        from official_workflow import completed
        completed(config)
        reviewer=council.read_json(work/'reviewer-latest.json')
        if set(reviewer['run_ids'])!={r['id'] for r in rows} or not Path(reviewer['receipt']).is_file():raise ValueError('최신 실험 결과에 대한 기존 Reviewer 기록이 필요합니다.')
        from official_review import completion
        official=completion(config,[r['id'] for r in rows])
        path=Path(payload['report'])
        if not path.resolve().is_relative_to(work) or path.is_symlink():raise ValueError('연구 작업공간의 최종 보고만 저장할 수 있습니다.')
        text=path.read_text()
        archive=Path(job['run_dir'])/'native-summary.md';archive.write_text(text)
        server.store.add_note(job['node_id'],'analysis','자율 연구 최종 보고',text[:99000])
        record=dict(job_id=job['id'],auto_session_id=session['id'],run_ids=[r['id'] for r in rows],report=str(archive),report_sha256=hashlib.sha256(text.encode()).hexdigest(),completed_at=now(),official_review=official)
        council.dump(work/'native-completion.json',record)
        retain_brief(server,job)
        return record
    raise ValueError('지원하지 않는 자율 연구 작업입니다.')


def retain_brief(server,job):
    path=Path(job['run_dir'])/'research-brief.json'
    if path.is_file():
        server.store.add_note(job['node_id'],'analysis','연구 보고 요약',path.read_text())
