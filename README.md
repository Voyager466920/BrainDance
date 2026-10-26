# BrainDance

```text
       ▗▉▉▉▉▉▉▉▉▉▉▄  ▗▉▉▉▉▉▉▉▉▉▉▄   ▗▄▟▉▉▉▉▉▉▉▙▖  ▟▉▉▉▘ ▟▉▉▉▉   ▟▉▉▉▌
       ▉▉▉▉▀▀▀▀▉▉▉▉▘ ▟▉▉▉▀▀▀▀▉▉▉▉▘ ▟▉▉▉▛▀▀▀▜▉▉▉▌ ▐▉▉▉▛ ▗▉▉▉▉▉▌ ▗▉▉▉▛
      ▟▉▉▉▙▄▄▄▟▉▉▛▘ ▐▉▉▉▉▄▄▄▄▉▉▉▀ ▗▉▉▉▉▄▄▄▄▉▉▉▛ ▗▉▉▉▉  ▉▉▉▉▉▉▉ ▉▉▉▉▘
     ▗▉▉▉▛▀▀▀▜▉▉▉▌ ▗▉▉▉▛▀▜▉▉▉▛    ▉▉▉▉▉▉▉▉▉▉▉▉▘ ▟▉▉▉▘ ▟▉▉▉▘▐▉▉▉▉▉▉▌
     ▉▉▉▉▄▄▄▄▟▉▉▉▘ ▟▉▉▉▘ ▝▉▉▉▙   ▟▉▉▉▘   ▐▉▉▉▌ ▐▉▉▉▛ ▗▉▉▉▛  ▉▉▉▉▉▛
    ▟▉▉▉▉▉▉▉▉▉▛▀  ▐▉▉▉▌   ▉▉▉▉  ▗▉▉▉▛   ▗▉▉▉▛ ▗▉▉▉▛  ▉▉▉▉   ▐▉▉▉▉▘

   ▗▉▉▉▉▉▉▉▉▙▖    ▗▄▉▉▉▉▉▉▉▉▄   ▉▉▉▉▙   ▟▉▉▉▘ ▗▄▟▉▉▉▉▉▉▉▉▉▘ ▟▉▉▉▉▉▉▉▉▉▉▉▌
   ▉▉▉▉▀▀▀▜▉▉▉▙  ▟▉▉▉▀▀▀▀▉▉▉▉▘ ▟▉▉▉▉▉▖ ▐▉▉▉▌ ▐▉▉▉▛▀▀▀▀▀▀▀▀ ▗▉▉▉▛▀▀▀▀▀▀▀▀
  ▟▉▉▉▘   ▐▉▉▉▌ ▐▉▉▉▉▄▄▄▄▉▉▉▛ ▗▉▉▉▛▉▉▙▗▉▉▉▛ ▗▉▉▉▉          ▉▉▉▉▙▄▄▄▄▄▖
 ▗▉▉▉▛   ▗▉▉▉▛ ▗▉▉▉▉▉▉▉▉▉▉▉▉  ▉▉▉▉▘▜▉▉▟▉▉▉▘ ▟▉▉▉▘         ▟▉▉▉▛▀▀▀▀▀▀▘
 ▉▉▉▉▄▄▄▟▉▉▉▛▘ ▟▉▉▉▘   ▟▉▉▉▘ ▟▉▉▉▘ ▝▉▉▉▉▉▌ ▐▉▉▉▉▄▄▄▄▄▄▄▖ ▗▉▉▉▉▄▄▄▄▄▄▄▖
▟▉▉▉▉▉▉▉▉▀▘   ▐▉▉▉▌   ▗▉▉▉▛ ▗▉▉▉▛   ▜▉▉▉▛  ▝▜▉▉▉▉▉▉▉▉▉▉  ▉▉▉▉▉▉▉▉▉▉▉▉▘
```

A local research workspace that explores papers, develops and reviews hypotheses, writes experiments, runs them on your selected hardware, and reports the actual results. The interface and research conversation are Korean-first.

## Install the macOS app

1. Download the Apple Silicon ZIP and `SHA256SUMS.txt` from [Releases](https://github.com/Voyager466920/BrainDance/releases/latest).
2. Verify the archive with `shasum -a 256 -c SHA256SUMS.txt`, then unzip it and move `BrainDance.app` to Applications.
3. Install and authenticate Claude Code and Codex CLI on the same Mac:

   ```sh
   codex login
   claude auth login
   ```

4. Set up the research engine and its documented prerequisites. Existing checkouts and Claude/Codex configuration are preserved.

Literature discovery and reviewer integration reuse [ARIS](https://github.com/wanshuiyin/Auto-claude-code-research-in-sleep); follow its official prerequisite instructions and install the checkout at `~/.local/share/BrainDance/research-engine`.

5. Open BrainDance, add a project, and select its local or SSH execution environment, devices and runtime budget.

The distributed app bundles its backend; Python and Node.js are not required to open it. Model tasks use the authenticated CLIs and their account usage. The app is ad-hoc signed and is not notarized. GPU frameworks, models and datasets must exist on the selected execution target; selecting a device does not reserve it against other software.

## Terminal / CLI

Install the terminal command from the macOS app, then start it:

```sh
"/Applications/BrainDance.app/Contents/Resources/BrainDanceServer" --install-cli
~/.local/bin/braindance
```

If `~/.local/bin` is already on your `PATH`, use `braindance` directly. The installer does not change your shell settings or overwrite an unrelated existing command. Python is bundled in the app.

Running `braindance` immediately displays a muted green **BrainDance** wordmark with broad oblique strokes, cut corners, and a static scanline texture. Normal and narrow terminals stack the words; wide terminals show one line. Use `--no-banner`, `--no-color`, or `NO_COLOR=1` to simplify it. The separate `--banner` command has been removed. There is no flashing animation. The original lettering is shipped as text assets and can be regenerated with `python3 desktop/make_terminal_logo.py`; no font or image library is needed at runtime.

The default terminal is a mouse-enabled workspace with seven bottom tabs: **대화** (Conversation), **진행** (Progress), **아이디어** (Ideas), **계획** (Plans), **실험** (Experiments), **설정** (Settings), and **결과** (Results). The project input stays in place across tabs. Structured reports are rendered as labelled prose; the original JSON, code, evidence and error logs remain stored unchanged.

- Click a tab, use **Alt+1–7**, or press **Ctrl+B** followed by **1–7**, **N** (next), or **P** (previous). **Ctrl+P** opens the project selector. Mouse/trackpad wheel and PageUp/PageDown scroll records, including long wrapped Korean paragraphs. Reading older messages suspends automatic scrolling when reports arrive; Ctrl+B then G or **최신** returns to the newest entry.
- Write naturally from any tab. Enter sends, Alt+Enter adds a newline, and Ctrl+O cycles between conversation, question only, next-step direction, and stop-and-reprepare. Drafts are preserved across tabs and kept separately for each project.
- The header shows the actual pipeline stage, automatic state, model-call usage, selected local/SSH target and devices. The stage bar indicates position in the pipeline, not an estimated training completion percentage. Experiment views show observed elapsed time, retained output, measured results and remaining runtime budget.
- GPU discovery records the server hostname, physical NVIDIA GPU index and UUID. GPU indexes start at **0**, exactly as reported by `nvidia-smi`; the CPU entry does not change GPU numbering. The selected target is checked in the background at most once per minute while this terminal is open. Receipts are timestamped; an unavailable GPU index is shown as unknown rather than guessed from list order. Settings also shows the latest GPU memory/utilization receipt.
- Progress has automatic start/pause/resume/stop and budget controls. **문제에 답글** (Reply to issue), **가설에 지시** (Direct hypothesis), **계획에 지시** (Direct plan), and **실험에 지시** (Direct experiment) return to the same project conversation with the relevant context. A direction for the next step leaves currently running code intact; stop-and-reprepare is an explicit separate input mode.
- Ideas include paper evidence, novelty, feasibility and Council evaluations. Plans include proposed designs, registered execution plans and a read-only code viewer. Experiments include both live runs and retained results. New-project setup selects the target, devices and runtime before saving.
- Slash commands focus on setup: `/settings`, `/gpt`, `/claude`, `/ssh`, `/gpu`, `/projects`, `/new`, and `/help`. Type `/exit` and press Enter to close the CLI, even while a message is being submitted; `/quit` remains an alias. Typing `/` opens completion suggestions. Account controls invoke the existing official CLI login flow only when you choose Login; credentials are not placed in research messages.

The terminal uses the app's existing local API, conversation stream, project Codex session, target selection, and budgets. GUI and terminal messages and research reports are shared. Model-backed replies consume connected-account usage and the existing session budget. Closing the terminal with Ctrl+Q or `/exit` disconnects the view without cancelling server work. `braindance --plain` retains the earlier line-oriented console and its `/use`, `/ask`, `/history`, `/reply`, `/auto`, and `/limits` commands.

The shared input sits in a fixed green frame at the very bottom, with navigation hints above it. List/detail views use separate blue-toned list panels, darker detail panels, labelled borders, and a highlighted selection; the same boundaries remain visible without color. Scrolling a record never moves the input or edits its draft.

Commands also work without an interactive terminal; `--json` produces plain machine-readable output without a logo or colors:

```sh
braindance projects
braindance --project "My project" status
braindance --project "My project" chat "Summarize the blockers" --mode ask
braindance --project "My project" history --full --json
braindance new "CPU pilot" --goal "Compare two small classifiers" --target local --devices cpu --minutes 10
braindance connections
braindance connection my-ssh-alias
braindance devices my-ssh-alias
braindance --project "My project" target my-ssh-alias --devices GPU-UUID --minutes 30
braindance --project "My project" auto start --context /path/on/target --calls 40 --tokens 1500000 --cycles 3
```

Creating a project does not start model calls or experiments. `devices` actually checks the selected connection; remote/GPU assignments require a recent successful discovery. `auto start` explicitly authorizes the reviewed pipeline on the selected devices within the specified limits, just like the app button. Raising limits preserves used amounts and does not resume work by itself. `chat --no-wait` returns immediately; subsequent `history` shows the reply. Supply the same `--request-id` and exact message/mode to check an uncertain send without duplicating it.

By default, the CLI attaches to `http://127.0.0.1:8766` or starts one detached local backend when none is running. It checks the workspace identity before connecting and refuses a different workspace. Start the CLI first if you want a backend independent of the GUI's lifetime; an already-running GUI-owned backend remains owned by that app. The private backend log is `~/Library/Application Support/BrainDance/cli-backend.log`. `--no-start` requires an existing server. For a separate workspace, use `--db /absolute/path/tree.sqlite3 --port 8770`; for an existing alternate port, use `--db ... --server http://127.0.0.1:8770`. Remote HTTP servers are not supported; SSH execution is handled by the same local backend.

## Results, visualization, and Notion

The app and CLI share a **결과 / Results** view and one publication queue per workspace. Build a report locally or publish it to a project-specific Notion parent page. Papers, hypotheses, Council evaluations, research analysis, and completed experiment receipts are grouped into a readable report. Successful runs with numeric primary metrics get labelled baseline/candidate or measured-value PNG charts. Failed runs remain in the report and are excluded from successful-comparison plots. A project with no measurements explicitly shows that no measured results are available.

The charts use retained values without inventing missing observations or statistical significance. Metrics with different names or optimization directions stay in separate plots. Reports include Markdown, the exact selected measurement/evidence data as JSON, PNGs, and run IDs for tracing the source. Original local code, receipts and error logs remain unchanged. Raw chat, runtime configuration, SSH credentials, device UUIDs, and connection tokens are excluded from the export.

**App:** open **Settings → Notion**, choose a project, enter its parent page URL and a Notion token, then select **연결 확인 · 저장** (Check and save). A blank token preserves an existing credential; without a saved credential it saves only the destination. Use a personal access token or internal connection with read/insert access; for an internal connection, add it to the parent page using the page's Connections menu. See Notion's [official quickstart](https://developers.notion.com/guides/get-started/quick-start) and [file upload guide](https://developers.notion.com/guides/data-apis/uploading-small-files).

**CLI:** `/notion` opens the same masked settings form. `/reports`, **Alt+7**, or **Ctrl+B then 7** opens Results. Use **시각화 열기** (Open visualization) to view the full PNG report in a browser. Commands also work outside the terminal workspace:

```sh
braindance notion setup --project "My research" --parent "https://www.notion.so/PAGE_ID"
# The token is requested through hidden terminal input, never a command argument.
braindance report build --project "My research"
braindance report status --project "My research"
braindance report open --project "My research"
braindance notion sync --project "My research"
braindance notion status --project "My research"
# Opt into automatic publication of this project's changed reports:
braindance notion setup --project "My research" --auto
```

You can also ask in the shared project conversation, for example **“결과를 시각화해서 보고서로 정리해줘”** or **“연구 결과를 노션에 정리해줘”**. The host queues the requested report, and completion receipts return to the same project stream. Question-only mode does not publish. Report generation and synchronization do not call additional models or start experiments; an ordinary model-backed conversation reply uses the existing project budget.

Enable **이 프로젝트 결과 자동 동기화** to publish changed project results in the background. It is off until enabled, and disabling it stops future automatic queueing. Disconnecting removes the saved token and stops queued Notion publications. Each project gets a managed child page; each distinct report gets an immutable snapshot. Unchanged reports reuse the existing job and page. The durable queue exposes pending/processing/completed/error states and reconciles previously written pages and blocks before retrying an interrupted upload. It never overwrites manually edited report content. Rate limits use Notion's Retry-After header. The direct uploader supports files up to 5 MiB each; larger originals remain local with an explicit error.

Connection credentials live in the workspace's private `integrations/notion-credentials.json` (mode 0600); they never appear in the research database export or API responses. Local reports live under `reports/PROJECT_ID/DIGEST/`. Permanently deleting a project removes its local reports and publication queue, freeing storage; reports already published to Notion remain there. Only the selected project's report content and chart files are sent to the configured Notion page.

## One conversation for each project

The **대화** (Conversation) tab contains the project’s shared stream of reports, your messages, and real Codex replies. One input stays pinned to the bottom while you switch between Research Overview, Progress, Research Notes, Council transcripts, and Experiments. Sending from any tab continues this same project conversation.

Problems appear in a compact notice above the tabs. Choose **답글** (Reply) to answer a specific problem; the source record and your reply stay linked in the main conversation and are supplied to the model. The sidebar icon hides or shows the project list, and each project’s arrow expands or collapses its hypothesis tree.

- Ask about progress, evidence, results or blockers while research continues.
- Use **대화 · 의도에 맞게 반영** for natural conversation. Clear direction changes become instructions for the next step; explicit pause/stop requests control this project.
- **질문만 · 방향 유지** answers without changing the research direction.
- **방향 변경 · 다음 단계** records your instruction immediately and keeps the current experiment intact.
- **지금 중지하고 다시 준비** stops current work and prepares a replacement under the new direction.
- Choose the whole project or the selected hypothesis as the message scope. Enter sends; Shift+Enter adds a newline.

Each project has one durable shared conversation session. Conversation replies, target exploration, code authorship, and result analysis continue the same official Codex MCP thread; different projects use different thread IDs. Calls on one project thread are serialized. Independent Council and Claude reviewer contexts remain separate, with the same frozen project directions and relevant history supplied to them. Full human conversation and research records remain in the private project workspace; prompts use a bounded recent window instead of repeatedly copying the whole archive.

Use natural commands such as **서버와 기존 코드를 탐색해줘** to request a read-only inspection, or **막힌 부분을 해결하고 설정한 장치와 남은 예산 안에서 실험과 분석까지 계속해** to resume an existing authorized automatic session. Asking a question keeps the current work unchanged. The host validates the selected target and existing session limits; a model cannot create execution authority or increase the budget. Inspection-only commands leave a paused or blocked automatic session paused or blocked.

The target broker indexes repositories fairly and supports bounded source reads, literal searches, file metadata, and static Python-environment metadata checks. It uses the selected local or SSH target and configured research folder. No model-authored shell commands run during exploration; source files are not imported or modified. Actual execution still requires an immutable generated plan, Claude review, matching resource signature, the selected device environment, and the existing time/concurrency/model limits. Requests, exact source excerpts, errors, and model usage receipts are retained. Genuine missing dependencies/data or exhausted limits stop with a concrete report.

The conversation has its own reply worker. Replies use timestamped actual state and retained result reports; they do not claim live results that were not observed. Messages, action receipts and original model responses stay in your private workspace. Replies consume connected-account usage; active automatic sessions include them in their shared model budget. Reopening the app marks interrupted replies explicitly and does not replay model calls silently.

The **실험 실행** (Experiments) tab keeps immutable plans, source code, and execution history under **실행 계획 · 코드 · 이전 실험**. Research launch controls and detailed automatic-session usage are available under **실행 설정** in Progress. Manual code entry remains an advanced option.

Use the project header **한도** (Limits) button to increase an existing run’s total model-call or token allowance later. Used calls, token charges, research history, GPU/time settings, and the project conversation session are preserved. Saving a larger limit does not resume paused or blocked work; ask the conversation to continue when ready. Models cannot increase these limits themselves.

## Project automatic mode

Automatic research uses one shared project token ledger across literature, Council, code generation, review and analysis; standalone mode presets do not impose a second independent token stop inside that session. The configured project limit and recorded usage are retained. Admission uses estimates, so an in-flight provider response can exceed its reservation; subsequent calls stop at the shared limit. Resuming a pre-commit Council admission stop reuses the same verified evidence and completed model receipts instead of rerunning them. The original job ID, model session, charges and prior failure logs are preserved; ambiguous partial calls and already-committed trees are not automatically replayed.

Each project tile has its own **자동모드** control, visible even when collapsed. Every new session starts paper discovery and hypothesis review at the project root, even when hypotheses already exist, then continues through experiment design, code authoring/review, self-tests, execution, analysis and a next-experiment decision.

Starting a session authorizes reviewed LLM-generated code on the selected project devices within the existing runtime budget; per-experiment human approval is unnecessary. Later iterations reuse the discovery evidence and actual result reports. Configure maximum experiments, model invocations, token admission budget, research mode and an optional target-side reference directory.

Pause allows current work to finish but starts no new automatic step. Stop cancels project work. Missing prerequisites, repeated identical code, consecutive failures or exhausted limits produce a report and stop. Changed directions invalidate unexecuted older plans; already-running code is never edited in place. Restarting the app pauses automatic sessions for explicit resume. Token limits are conservative admission estimates, not provider hard spending caps; in-flight usage can exceed estimates. Models cannot expand devices, budgets or permissions through chat.

## Local and SSH experiments

An explicit reference folder takes precedence. If it is blank, the host resolves folder names or paths from the original project goal and latest human directions on the selected target before inspecting source code. Discovery checks only those named folders at bounded workspace locations; it does not recursively scan the home directory, read credentials, or execute project code. A unique verified path is reused for the same automatic session while preserving its budget and history. Missing or ambiguous folders produce a specific error before spending model calls on code generation; the discovery receipts remain available in Progress.

Settings shows the current CLI authentication, reported subscription plan and available quota windows. Unknown plans or unavailable usage are labelled explicitly. Settings also supports SSH profiles, connection checks and GPU discovery. Existing keys, SSH agent and host aliases are used; private connection settings stay outside the repository.

Remote execution requires `python3`; NVIDIA discovery additionally requires `nvidia-smi`. Choose an installed Python environment for ML dependencies. The built-in runtime supports standard-library code. The app does not install remote packages or download models implicitly.

Experiments receive `BRAINDANCE_DEVICE`, `CUDA_VISIBLE_DEVICES`, `BRAINDANCE_GPU_IDS`, `BRAINDANCE_METRICS_PATH` and `BRAINDANCE_ARTIFACT_DIR`. Write actual measured JSON metrics such as `{"baseline":{"accuracy":0.5},"candidate":{"accuracy":0.7}}` and save artifacts under the provided directory. The runner preserves raw logs, exit status, metrics and artifact receipts. Observed differences do not establish statistical significance. The supplied synthetic CPU example verifies the execution infrastructure; it is not a paper reproduction or VLA validation.

## Run from source

Use Python 3.12 or later and the authenticated CLIs. Node.js is optional for the browser-script tests.

```sh
git clone https://github.com/Voyager466920/BrainDance.git
cd BrainDance
python3 -m venv .venv
.venv/bin/pip install -r requirements-cli.txt
.venv/bin/python braindance.py
```

One-shot CLI commands use the standard library; interactive input uses `prompt-toolkit`. To install a source-based `braindance` command, run `.venv/bin/python braindance.py install-cli`. To run the service in the foreground, use `.venv/bin/python braindance.py serve --db "$HOME/Library/Application Support/BrainDance/tree.sqlite3" --port 8766`. Stop an existing backend before starting another service on the same workspace; ordinary CLI commands attach to the current one. To use a different engine checkout, set `BRAINDANCE_ENGINE_DIR` to its absolute path before launching the backend. Legacy engine settings remain supported.

Build the native app on macOS:

```sh
python3 -m venv .venv
.venv/bin/pip install -r desktop/requirements-build.txt
.venv/bin/python desktop/build.py
.venv/bin/python desktop/check_cli_bundle.py dist/BrainDance.app
```

Run the offline automated checks:

```sh
python3 braindance.py --test
```

Tests use disposable databases, synthetic inputs, loopback HTTP and CPU subprocesses; model calls use fixtures unless an authenticated integration test is explicitly run. They do not require private research data or GPU execution.

## Private data and deletion

The app stores research, messages, model receipts, reports, databases, SSH profiles and account-status caches under `~/Library/Application Support/BrainDance/`. Account credentials remain managed by the CLIs and are not sent to the viewer. The application bundle contains no personal workspace data.

Projects support recoverable Trash and permanent deletion of app-managed local records and artifacts, including conversations. External datasets and source repositories are preserved. Remote experiment artifacts have their own target-side storage and are not silently deleted with local project data. Back up important work before permanently deleting it. Private runtime folders and build outputs are excluded from Git; do not publish credentials, SSH settings or research results accidentally.

## License

MIT. Reused Council design attribution and third-party notices remain in the source and app bundle. Claude Code and Codex CLI are separate products with their own terms.
