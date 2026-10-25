# Research jobs in BrainDance

An existing root problem can start from **연구 시작**. Creating a project defaults to **만들고 연구 시작**, with an explicit model-usage label; uncheck it to save only. Balanced is the default. Review mode and limits before confirming. Each job runs one Council and ends with **설계 완료 · 실험 승인 대기**. It does not generate or execute GPU training code, inspect remote repositories, or run autoresearch.

The host resolves the official ARIS checkout from `ARIS_REPO` or `~/aris_repo`, copies its unchanged `research-lit` Skill and shared references into a per-job plugin, records the Skill hash and requires a successful Skill invocation receipt. Claude receives only file/search/fetch tools in restricted mode; it uses the upstream workflow's sequential extraction tier. The host then runs the unmodified official `arxiv_fetch.py` and `verify_papers.py` helpers. Identity verification is not claim/novelty verification. Original abstracts replace model-provided summaries only when actually retrieved. Failed/unverified sources remain labelled, never promoted by assumption.

The existing Council reuses the same three Claude specialists, independent Codex generation/review via the official ARIS MCP bridge, anonymous cross-review and Chairman synthesis. It persists the actual requests/responses, model usage, tree branches, proposed controls, metrics and rejection rules. No duplicate ARIS Reviewer is invoked.

The UI polls persisted job states and shows stage names rather than invented percentages or ETAs. Node green/active describes eligibility; **진행 중** describes a running job. Progress logs contain stage events, not private model reasoning. Evidence/report/usage files are downloadable. Global Claude/Codex configuration is unchanged.

Only one research job can run per workspace. Duplicate start while that project is running returns its existing job. A different project must wait. Stage timeout is configurable (60–1800 seconds); the Council token limit is an admission/stop budget, not a hard billing ceiling. The literature Claude session also has its own dollar limit. Other Council sessions retain their per-session limits. Report aggregate observed usage separately from limits.

The app permits up to 6,000 response tokens per Claude Council response so four-way Korean reviews fit; this overrides the standalone runner's smaller presets. Reviews request concise rationales. These are per-response limits, not total session-token ceilings. If a call still fails or truncates, preserve its failure and actual usage instead of inventing a vote.

**동일 목표의 저장된 논문 근거 재사용** is enabled by default. When an earlier job on the same project/topic has saved verified evidence and an actual Skill receipt, a new job copies those artifacts and records their source job without another literature model call. Uncheck it for a fresh search. Council is a new execution; no failed vote is silently credited as successful and previous call costs are not claimed as new usage. Prior runs remain accessible through the progress dialog's execution-history selector.

Stop sends termination to the worker, which terminates active CLI/MCP process groups. Quitting the app stops app-owned research. Abrupt restart marks unfinished jobs interrupted and does not replay requests. Stop/failure preserves completed artifacts. A new launch is a new run, not a hidden retry. Existing experiment executors remain separately bounded and approved.

Research jobs are stored in SQLite and mirrored in tree JSON. Their per-job folders live under the managed `council-runs/` directory; permanent project deletion handles them, blocks active/finishing jobs and preserves folders referenced by another project. Backups and source/model caches retain their existing retention policy.
