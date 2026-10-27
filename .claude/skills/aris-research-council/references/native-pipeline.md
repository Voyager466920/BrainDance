# Native research pipeline integration

## Ownership

New project automatic sessions use `pipeline=aris-native`. `native_pipeline.py` loads **unmodified installed** ARIS Skills and invokes `aris-official:research-pipeline` in Claude Code. Actual successful Skill-tool receipts are required for the main pipeline and `idea-discovery`, `experiment-bridge`, `auto-review-loop`. The original Reviewer still runs through the official `codex-exec` MCP bridge; Council is additional advice at the idea/result boundaries.

The official pipeline owns scientific sequencing, source implementation, debugging, result interpretation, reviewer feedback and stopping decisions. `Autopilot.native_tick` merely starts/supervises that session. It does not run the former draft → author → analysis decision loop. Paper writing stays optional/off by default.

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
