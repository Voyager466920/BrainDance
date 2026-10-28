# Native research pipeline integration

## Ownership

New project automatic sessions use `pipeline=aris-native`. `native_pipeline.py` loads **unmodified installed** ARIS Skills and invokes `aris-official:research-pipeline` in Claude Code. Actual successful Skill-tool receipts are required for the main pipeline and `idea-discovery`, `experiment-bridge`, `auto-review-loop`. The original Reviewer still runs through the official `codex-exec` MCP bridge; Council is additional advice at the idea/result boundaries.

The official pipeline owns scientific sequencing, source implementation, debugging, result interpretation, reviewer feedback and scientific batch completion decisions. In deadline-only mode the host archives each completed batch and starts the next scientific cycle until the absolute deadline. `Autopilot.native_tick` merely starts/supervises that session. It does not run the former draft → author → analysis decision loop. Paper writing stays optional/off by default.

Failed workers recover the same authorization, project workspace and model usage ledger after a durable backoff. The main executor receives original failure logs and diagnoses imports, environments, code and metrics itself. Failed/unmeasured executions do not consume completed-measurement slots; actual runtime and every model charge remain counted. Do not complete an all-failed scouting batch as a valid negative result. Authentication, held/discarded projects, changed resources and exhausted budgets require the corresponding user action; automatic recovery cannot expand authority. Properly measured negative results are valid completions.

## Host tools

The native session loads a local MCP transport named `codex`:

- `context`: same project conversation, latest human directions, selected resources and remaining limits.
- `target`: existing read-only local/SSH inventory and bounded source reads.
- `helper`: limited original upstream bookkeeping/paper tools, including `run_state.py`; no arbitrary shell or generated-code execution.
- `codex` / `codex-reply`: original independent Reviewer, through the real upstream bridge and existing project Codex session/accounting.
- `council`: actual three-Claude/one-Codex advisory Council, with upstream literature verification and retained original evidence.
- `experiment`: source written by the native executor → exact-code independent review → immutable plan → selected-device execution through the existing broker. Each pilot/retry consumes the same project run/time allowance.
- `receipt`: actual exit state, metrics and logs from that run.
- `finish`: retain the final report after real measurements, both Council advice stages and Reviewer receipts. The worker also verifies the actual official Skill calls before marking the job complete.

Bash/SSH and unrestricted Agent execution are unavailable to the main process so it cannot bypass device/runtime accounting; official workflows use their sequential fallback. The Council's existing isolated native subagents are unchanged. This is a host-tool adaptation, not an assertion that every upstream tool, installer, external queue or paper-writing integration is supported.

## Persistence, intervention and budgets

The Claude session/workspace lives under the existing project session; job traces and final report snapshots remain per job. A resume continues the Claude session and upstream `.aris/runs` state. A new authorization begins a new upstream run without erasing earlier context/results. Changes to user directions invalidate a source review before dispatch; active experiments keep their exact code.

Pause/stop/resource changes stop new host actions and interrupt the main native process. Resume uses the same workspace. An interrupted model reservation remains charged. Main Claude message IDs, original Reviewer calls and Council participants use the shared ledger. Estimates admit calls; observed usage can exceed an estimate, as in the existing budget contract. Do not call a turn count a billed-token cap.

An already-running `discovery-to-results` session keeps its controller until it stops. New sessions use the official pipeline. When the human resumes an inactive legacy session, retain its prior pipeline/progress as migration history and switch to the native executor with the same project conversation, ledger, limits, devices and results. Never silently raise a budget or change a running job.

## Validation

Distinguish offline transport checks (mocked model answers), real CPU executor checks, and an actual native research run. Only the last demonstrates live official Skill participation; report its exact completed stages and any blocker. A failed or incomplete live run is not an end-to-end success.

Successful original Skill receipts are reused across interrupted jobs within the same automatic authorization/workspace/scientific cycle. Earlier cycles cannot satisfy current Skill receipts. Source traces remain linked per job; unrelated sessions cannot borrow them. Local context/receipt/triage reads and final report storage do not spend another model call. If a model already requested finish but budget admission stopped local bookkeeping, resume replays only that exact finish request against the normal host verifiers. A successful host finish terminates the closing CLI turn rather than requiring an extra conversational sign-off. Stream usage remains distinct from an unavailable final aggregate receipt.

## Deadline-only execution

Default CLI/UI starts explicitly select `execution_policy=until_deadline`. Only wall-clock time limits the run: model calls, tokens, dollars and experiment counts are accounting fields, not stop limits. The main Claude invocation has no `--max-turns` or `--max-budget-usd`; nested Council uses the shared uncapped ledger. Provider limits cannot be bypassed. The host enforces the absolute deadline in admission, native model supervision, experiment dispatch and target process supervision. It cancels in-flight work at expiry and writes a local final status without spending another model call. Existing projects can convert with `action=time_only` while preserving usage, devices, session and history. Extending time uses `action=deadline`; models cannot grant themselves more time. Completed batches increment `native_cycle`, retain immutable per-job artifacts and begin a fresh upstream run in the same workspace. Original review-loop rounds are not timer-wrapped or reset. Backend restarts retain the deadline and continue supervision.
