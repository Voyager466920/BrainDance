# Changelog

## 0.19.19

- Install the original full project-local Skills and aris-fanout-leaf with the official installer. Remove restricted-mode discovery suppression and the Agent ban. Preserve original source snapshots and archive legacy plugin/session state during migration.
- Replace the custom mandatory exploration coordinator with the original idea-discovery/idea-creator phases, native lens fan-out, Codex brainstorm and original pilot flow. Council remains additional advice. Show real phase narration, searches and Agent activity in progress records.
- Preserve raw native Codex slot responses and original fresh-call/reply semantics; brainstorms after a pilot are no longer misclassified as result-review rounds. Original review-gate logic remains unchanged.
- Keep selected-resource experiment enforcement through the broker while allowing original helper and local bookkeeping shell calls. Add Ghostty keyboard instructions and packaged bindings.

## 0.19.18

- Handle legitimate string-valued Claude system notifications and mixed stream records without losing actual Skill/tool receipts or breaking task resumption.
- Include actual worker tracebacks in recovery diagnosis, rather than referring to nonexistent native streams after preflight failure.
- Add a detached host repair worker: generate an exact patch in a registered source snapshot, replay the failure, run unchanged regression tests, build/check a CLI candidate, deploy while research is idle and retain the previous immutable runtime for rollback. Keep original ARIS and resource/allowance/review controls unchanged.
- Retain the same project/session/tasks and require real resumed tool success before recovery confirmation. Detect detached worker exits and preserve explicit user stops, deadlines and charged usage. Register the local build source automatically on CLI installation; add `monitor repair-source` for separately installed source/build environments.

## 0.19.17

- Execute the installed, unmodified research review helpers, including `review_gate.py`, reviewer routing and trace recording, through the existing managed transport. Original Skills and helper source remain unchanged.
- Require original review state, real per-round Reviewer/helper receipts and cumulative review/memory before accepting measured-study completion. A single negative review can no longer close a study early; the upstream gate and original round limit decide termination. Exhausted negative reviews remain unresolved.
- Keep experiment checks and advisory Council separate from research-review rounds. Preserve the actual Reviewer thread ID and full raw response for original round continuation and tracing. Interrupted work and existing research records remain intact.

## 0.19.16

- Connect the external monitor to a durable, guarded repair queue. A read-only Codex adviser diagnoses actual tool errors and returns concrete feedback to the same official research workspace; verify the failed operation succeeds before marking recovery confirmed.
- Keep existing deadlines, allowance guards, devices, histories and reviewed experiment limits. Hold repeated failures for diagnosis, deduplicate repairs and bound diagnosis attempts. Honor pause/stop and preserve ambiguous interrupted calls.
- Recover unavailable registered immutable backends after three health failures; preserve valid GPU runs and refuse unrelated processes or changed executable images. Add `monitor repair-on` / `repair-off`.
- Normalize explicit paper identifier aliases and candidate containers without overwriting raw retrieval files or skipping fresh official verification. Fix misleading paper-count errors for `{papers: [...]}` candidates and canonical-ID-only sources.

## 0.19.15

- Pin frozen CLI and backend images at immutable, content-hashed paths. Updating the installation no longer replaces the archive used by running processes and lazy imports.
- Freeze Council scientific inputs independently of volatile verification timestamps and attempt paths. Retry unchanged inputs with strict resume checks; retain all prior attempt logs and start a new Council for changed evidence or results.
- Recover completed Council tree commits and import retained conversation history without another model call. Keep incomplete commits blocked; a failed history import no longer invalidates completed research.
- Enable Python fatal-signal traces in supervised experiments so native aborts retain their Python stack in the original stderr log.

## 0.19.14

- Add an independent, standard-library-only macOS monitor that performs one short check per minute.
- Read research state and bounded logs without model calls, SSH polling, research-record changes or automatic restarts. Ignore idle/stopped/expired sessions and valid long experiments.
- Send deduplicated stall, repeated-error and backend-availability alerts to the existing personal Slack destination; respect muting and hold ambiguous deliveries.
- Add `braindance monitor install`, `status`, `check --no-notify` and `uninstall`, which work independently of backend startup.

## 0.19.13

- Fix paper-verification loops where a slow lookup exceeded the 240-second batch limit before the official verifier saved its results and cache.
- Reuse the original verifier's valid cache, check uncached papers independently with bounded time, and save each completed receipt. Preserve raw attempts and leave transient failures as `verify_pending` with a retry cooldown.
- Use confirmed readable sources for the six exploratory agents while retaining excluded sources and diagnostics. Identity confirmation still does not establish novelty; original fresh searches and independent review remain required.
- Show paper-verification counts separately from exploration-agent completion counts.

## 0.19.12

- Add an independent experiment with `새 실험:`, `실험 추가:` or `new experiment:` in a selected Slack project/thread or CLI conversation in auto mode.
- Save an unverified hypothesis and durable request with an immediate acknowledgement and no LLM call for registration.
- Route requested studies through the existing official pipeline and execution broker, retaining the selected devices, deadline, reviews, allowance guard and shared project conversation.
- Save requests for stopped/paused/expired projects without resuming research. Requests made before a research session wait for authorized CLI setup.
- Suppress duplicate request IDs and keep human requests separate from verified discovery candidates. Include requests in exports and permanent project cleanup.
- Clarify that authenticated Claude accounts can encounter HTTP 429 on account-usage retrieval independently of model responses.
- Validation: 353 automated tests and standalone CLI package checks passed, including real CPU subprocess measurements with offline model/Skill fixtures. A separate live Claude Haiku connectivity probe returned `OK`. These checks do not establish new GPU research results.

See [experiment requests](docs/experiment-requests.md) and [Slack setup](docs/slack.md).

## 0.19.11

- Receive registered-owner personal DMs through the official Slack SDK and Socket Mode.
- Support project selection, shared natural-language conversations, status/allowance, stop/pause and explicit time/allowance continuation commands.
- Bind existing Slack threads to their original project and retain event IDs/outgoing reply records for duplicate suppression and crash recovery.
- Add hidden app-token setup through `/slack remote` and terminal connection/disconnection commands while preserving outgoing result notifications.
- Validation: 343 automated tests and standalone CLI package checks passed. Live incoming setup requires the owner's app-level token and Slack event permissions.

## 0.19.10

- Continue stopped or completed research in the same project/session with a fresh execution window and selectable account-allowance decrease.
- Preserve conversation, task workspaces, scientific results and cumulative usage while retaining previous stop-policy checkpoints.
- Distinguish Claude authentication from rate-limited account-usage retrieval.

[Release downloads](https://github.com/Voyager466920/BrainDance/releases)
