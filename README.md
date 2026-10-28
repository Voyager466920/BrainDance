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

Brand icon: [horizontal BD monogram](assets/branding/braindance-cyberpunk-icon-v3.png).

## Install the standalone CLI

Download `BrainDance-cli-macOS-arm64.zip` and `SHA256SUMS.txt` from [Releases](https://github.com/Voyager466920/BrainDance/releases/latest). Verify the archive checksum, unzip it, and install independently of the desktop app:

```sh
mkdir -p ~/.local/share/BrainDance/cli
cp -R BrainDanceCLI/. ~/.local/share/BrainDance/cli/
~/.local/share/BrainDance/cli/BrainDanceServer --install-cli
~/.local/bin/braindance
```

If `~/.local/bin` is on your `PATH`, use `braindance` directly. The CLI bundles Python, assets and dependencies; `BrainDance.app` is not required. The installer does not modify shell settings or overwrite an unrelated command. Source installs work with `python3 -m pip install -r requirements-cli.txt` and `python3 braindance.py install-cli`.

Install and authenticate the official model CLIs:

```sh
codex login
claude auth login
```

The main autonomous pipeline, its nested research Skills, and its original independent Reviewer reuse [ARIS](https://github.com/wanshuiyin/Auto-claude-code-research-in-sleep); Council adds advice after idea discovery and after measured results while the official pipeline drives implementation, experiments and review iterations. Follow its official prerequisite instructions and install the checkout at `~/.local/share/BrainDance/research-engine`.

GPU frameworks, models and datasets belong on the selected local/SSH target. Selecting a device does not reserve it against other software. Tasks use the authenticated CLI accounts and their usage. The optional app/browser UI shares the same project settings and backend; building the native app is optional. Build a standalone executable using `python3 desktop/build_cli.py` after installing `desktop/requirements-build.txt`.

## Terminal / CLI

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
braindance --project "My project" auto start --context /path/on/target --hours 8
```

Manage projects from either the terminal workspace or one-shot commands:

```sh
braindance delete --project "My project"                    # Stop research and move to Trash
braindance trash                                          # List trashed projects and pending cleanup
braindance restore --project "My project"                   # Restore without resuming research
braindance purge --project "My project" --preview            # Preview records and managed local file size
braindance purge --project "My project"                      # Ask for the exact project name in a terminal
braindance purge --project PROJECT_ID --confirm-name "My project" # Explicit confirmation for scripts
```

The project menu (`Ctrl+P` or `/projects`) includes Delete and Trash. `/delete` opens confirmation for the current project; `/trash` opens Restore and Permanently delete actions. Permanent deletion requires typing the exact project name and cannot be undone. Use a project ID if names are duplicated. These commands share the app's lifecycle and cleanup APIs: local managed results, conversation/session records, reports and database space are cleaned up, while SSH server files and external source/data folders are preserved. Incomplete cleanup remains visible in Trash and can be retried; scripts receive a nonzero exit status. Noninteractive purge requires `--confirm-name`; `--preview` never deletes anything.

Keyboard navigation works throughout the terminal workspace. In project, Trash, server/GPU and mode lists, arrows select the highlighted item; Down at the final item moves into the next field or action buttons. Up from buttons returns to the form/list, Left/Right selects buttons, and Tab/Shift+Tab cycles fields and actions. Enter on a highlighted project opens it directly. Focus the tab strip to change tabs with Left/Right; Enter returns to the composer. `/keys` shows the complete guide.

Input fields use whitespace boundaries for word movement/deletion, preserving punctuation inside paths and Korean words. Ctrl+Left/Right or Option+Left/Right moves by word; Option+Backspace and Ctrl+W delete the previous word. These bindings also apply inside settings dialogs. For iTerm2 Command+Left/Right and Command+Backspace, import [BrainDance.itermkeymap](desktop/BrainDance.itermkeymap) in **Settings → Profiles → Keys → Key Mappings → Presets → Import** for your BrainDance profile. Choose **Keep** existing mappings if prompted; the file changes only those three Command shortcuts. The app also includes the file at `BrainDance.app/Contents/Resources/BrainDance.itermkeymap`. Terminal-owned Command shortcuts must be forwarded before a terminal application can receive them; the CLI never modifies iTerm2 preferences automatically. See the [iTerm2 key mapping documentation](https://iterm2.com/documentation-preferences-profiles-keys.html).

In the terminal new-project wizard, select hardware, choose **다음 · 연구 시작**, enter **총 연구 시간** once in hours, then select **만들고 자동 시작**. The hardware screen only selects the server, devices and concurrency; it has no second time budget to match. Experiments share the resulting project deadline and allocate their time automatically. **만들기만** saves without starting. One-shot `new` supports `--start --hours 8`, `--context` and `--mode`; without `--start`, creation does not call models or run experiments. `devices` actually checks the selected connection; remote/GPU assignments require a recent successful discovery. `auto start` explicitly authorizes the reviewed pipeline on the selected devices within the specified limits, just like the app button. Changing the deadline preserves all recorded usage and history. `chat --no-wait` returns immediately; subsequent `history` shows the reply. Supply the same `--request-id` and exact message/mode to check an uncertain send without duplicating it.

The default automatic session repairs failed experiments in its existing workspace. Advanced legacy bounded sessions can explicitly use `auto start --bounded --reuse-research` with `--context`, `--cycles`, `--calls`, and `--tokens`. This requires completed Council results, verified literature receipts, and active hypotheses in the same project. It skips discovery and Council calls while generating and reviewing fresh executable code against the current target and directions. Prior sessions, failures, and token charges remain recorded; the new session has its own model budget, and prior experiment runtime still counts against the unchanged project device/time assignment.

By default, the CLI attaches to `http://127.0.0.1:8766` or starts one detached local backend when none is running. It checks the workspace identity before connecting and refuses a different workspace. Start the CLI first if you want a backend independent of the GUI's lifetime; an already-running GUI-owned backend remains owned by that app. The private backend log is `~/Library/Application Support/BrainDance/cli-backend.log`. `--no-start` requires an existing server. For a separate workspace, use `--db /absolute/path/tree.sqlite3 --port 8770`; for an existing alternate port, use `--db ... --server http://127.0.0.1:8770`. Remote HTTP servers are not supported; SSH execution is handled by the same local backend.

## Paper scouting

Each project stores its own interests and optional bridge fields. Leave bridge fields empty to let the main executor choose adjacent fields and record its rationale. Scouting retrieves recent papers and explicitly labelled older cross-domain papers, retains real source receipts, and avoids re-testing completed connections. The normal main research executor and original independent Reviewer remain in charge; full Council review is reserved for measured promising results in scouting mode.

```sh
braindance new "Edge research" --goal "Transfer ideas to on-device adaptation" --style scout --interest "on-device adaptation" --bridge "control theory" --target local --devices cpu --minutes 5
braindance interests --project "Edge research" --days 30 --pilots 2 --seconds 60 --gain 0.05 --seeds 3
braindance scout start --project "Edge research"
braindance scout status --project "Edge research"
# Or create and start in one command:
braindance new "Fresh pilot" --goal "Test paper transfers" --style scout --interest "edge adaptation" --devices cpu --minutes 5 --start --calls 80 --tokens 3000000
```

Use `/interests` and `/scout` in the terminal workspace. The app/browser provides the same project interest form and research-style selector. Promising reports appear in the same project conversation with source links, measured comparisons, seed values, limitations and next steps; negative pilots stay in the journal.

Experiment time is allocated automatically. In default deadline-only mode, all work shares the absolute project deadline: there is no model-call, token, dollar or experiment-count stop limit. A pilot receives a suggested runtime (15 minutes for scouting, 30 for focused studies) and can request more within the remaining project time. Code receives `BRAINDANCE_TIMEOUT_SECONDS` and `BRAINDANCE_DEADLINE_UNIX`; the target supervisor enforces the grant. Legacy `--bounded` mode retains experiment-slot allocation and optional fixed per-pilot limits.

The default screen requires 5% relative improvement, three distinct measured seeds and improvement in at least two thirds of the seeds. Aggregate metrics must agree with seed means. This is pilot triage, not a significance test or novelty claim. Maximize/minimize metrics are supported; zero baselines remain inconclusive. Source errors and missing results stay explicit. Each scientific batch records its findings, then default automatic mode starts the next batch until the deadline. A successful pilot or a valid negative result does not stop the project. No external recurring scheduler is needed.

## Results, visualization, and Notion

The app and CLI share a **결과 / Results** view and one publication queue per workspace. Build a report locally or publish it to the shared Notion destination. Papers, hypotheses, Council evaluations, research analysis, and completed experiment receipts are grouped into a readable report. Successful runs with numeric primary metrics get labelled baseline/candidate or measured-value PNG charts. Failed runs remain in the report and are excluded from successful-comparison plots. A project with no measurements explicitly shows that no measured results are available.

The charts use retained values without inventing missing observations or statistical significance. Metrics with different names or optimization directions stay in separate plots. Reports include Markdown, the exact selected measurement/evidence data as JSON, PNGs, and run IDs for tracing the source. Original local code, receipts and error logs remain unchanged. Raw chat, runtime configuration, SSH credentials, device UUIDs, and connection tokens are excluded from the export.

**Shared connection:** open **Settings → Notion** or `/notion`, enter the parent page URL and token once, then save. No project needs to exist or be selected. Like Slack, the connection persists across CLI/backend restarts and new projects automatically inherit it. Saving the terminal form enables automatic publication for all projects. A blank token preserves the existing credential. Use a personal access token or internal connection with read/insert access; for an internal connection, add it to the parent page using the page's Connections menu. See Notion's [official quickstart](https://developers.notion.com/guides/get-started/quick-start) and [file upload guide](https://developers.notion.com/guides/data-apis/uploading-small-files).

**CLI:** `/notion` opens the same masked settings form. `/reports`, **Alt+7**, or **Ctrl+B then 7** opens Results. Use **시각화 열기** (Open visualization) to view the full PNG report in a browser. Commands also work outside the terminal workspace:

```sh
braindance notion setup --parent "https://www.notion.so/PAGE_ID"
# The token is requested through hidden terminal input, never a command argument.
braindance report build --project "My research"
braindance report status --project "My research"
braindance report open --project "My research"
braindance notion sync --project "My research"
braindance notion status
# Connection setup defaults to automatic publication; only manual sync needs a project.
```

You can also ask in the shared project conversation, for example **“결과를 시각화해서 보고서로 정리해줘”** or **“연구 결과를 노션에 정리해줘”**. The host queues the requested report, and completion receipts return to the same project stream. Question-only mode does not publish. Report generation and synchronization do not call additional models or start experiments; an ordinary model-backed conversation reply uses the existing project budget.

Automatic publication follows completed experiment records or a readable research summary. Empty projects, running-only experiments and internal review chatter do not generate repeated pages. The previous verified destination becomes the default on upgrade; credentials, published reports and queue history are preserved. Disconnecting removes the saved token and stops automatic and queued Notion publications for all projects, including future ones. New connections create an inline **BrainDance 연구 기록** database below the selected parent, with a date-sorted table and calendar. **Each project has one stable page and database row.** Its title and latest result properties update in place, including after a project rename. Each distinct report is a dated, collapsible section inside that page, newest first, with its Markdown and chart attachments. Older report pages are moved intact beneath the project's **이전 기록** (Previous records) child page on its next synchronization; their contents and original links remain available. Repeated synchronization reconciles the project key, report section and existing blocks before writing, including after an uncertain network response. Previously configured page-layout destinations likewise reuse their project page. Network/server failures retry automatically with backoff; missing credentials or page access require a connection change. Human notes outside report sections remain untouched; edits inside an incomplete section stop its retry rather than being overwritten. Rate limits use Notion's Retry-After header. The direct uploader supports files up to 5 MiB each; larger originals remain local with an explicit error.

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

**논문을 찾아줘** requests actual external literature discovery and source verification, even when the project has no papers yet. In a paper-survey project, **탐색 시작해** also queues this worker directly without an extra reply-model call. Progress and the literature report appear in the same conversation. This action does not create automatic experiment authority, connect to the selected GPU, or prepare/run experiment code; a paper-only request stays paper-only. Question-only mode never queues it.

The new-project wizard keeps your draft while moving backward through research settings, hardware, and launch options. Interest and bridge-field lists each allow up to 12 short entries; these are checked before leaving the first step. Put the full interdisciplinary research brief in the research goal, and leave bridge fields blank for automatic selection. The existing-code reference folder is optional: use it when you want the selected target's repository inspected; experiment outputs are stored in separate run workspaces.

The target broker indexes repositories fairly and supports bounded source reads, literal searches, file metadata, and static Python-environment metadata checks. It uses the selected local or SSH target and configured research folder. No model-authored shell commands run during exploration; source files are not imported or modified. Actual execution still requires an immutable generated plan, Claude review, matching resource signature, the selected device environment, and the existing time/concurrency/model limits. Requests, exact source excerpts, errors, and model usage receipts are retained. Genuine missing dependencies/data or exhausted limits stop with a concrete report.

The conversation has its own Codex reply worker and a separate per-reply budget. **Questions and summaries continue after the research deadline or an exhausted research budget**, using the same project history and Codex thread. They do not resume experiments, Council or automatic research. The host checks the original human message before applying a model-selected action; planning questions, summaries, quoted instructions and logs do not authorize execution. Explicit experiment requests still require a valid research deadline and resources; a reply never extends those limits. Replies consume connected-account usage, with their own usage receipts rather than charging the expired research ledger. Resumed Codex usage uses the current invocation delta when native session counters verify the cumulative provider receipt; the original provider counters are retained. They use timestamped actual state and retained result reports and do not claim unobserved live results. Messages, action receipts and original model responses stay in your private workspace. Reopening the app marks interrupted replies explicitly and does not replay model calls silently.

The **실험 실행** (Experiments) tab keeps immutable plans, source code, and execution history under **실행 계획 · 코드 · 이전 실험**. Research launch controls and detailed automatic-session usage are available under **실행 설정** in Progress. Manual code entry remains an advanced option.

Use **한도** (Limits), `/limits`, or `braindance limits --hours 8 --project "My project"` to change the remaining time. Recorded usage, scientific history, device selection and the shared project conversation remain intact. The new end time is measured from the moment the change is saved. Paused or stopped work still requires an explicit resume/start.

## Personal Slack DM result notifications

BrainDance can send completed-study summaries directly to your personal Slack DM without making any extra model calls. Each message uses the retained study problem, method, actual measurements and limitations; a matching Notion report links the full implementation references and charts. With Notion auto-sync enabled, notifications wait briefly for its matching report. Discovery-only progress and every small retry are not sent. Each study is queued once; ambiguous network responses are held for inspection instead of blindly posting duplicate DMs. Known rate limits retry after Slack's delay.

Notifications are sent when each hypothesis study finishes its report, including a documented pre-experiment rejection, rather than waiting for the whole project deadline. The background sender checks every three seconds; a matching Notion report may add up to three minutes, plus any delivery queue or Slack rate-limit delay. Rejection DMs explicitly say no experiment or measurement was performed.

Create a Slack app from [the included manifest](.claude/skills/aris-research-council/assets/slack-app-manifest.json), grant its bot **chat:write** and **im:write**, and install it in your workspace. Copy its **Bot User OAuth Token** and your own **member ID** from your Slack profile. In the terminal, open `/slack` (or Settings → Slack DM), enter your member ID and the token in the hidden field, and save. Saving checks authentication and opens the personal bot DM; it sends no test message. The **테스트 DM** button explicitly sends a test. This local background integration is separate from the Codex chat's Slack connection and keeps its token in a private file on your Mac, never in Git, research prompts or result reports.

Slack is a **global connection for all projects**, including projects created later. No project needs to exist or be selected for `/slack`, setup, status, test DM or disconnect. Each completed-study DM names its project; archived projects and discovery-only jobs are skipped. One-shot commands are `braindance slack setup --member U…`, `slack status`, `slack test` and `slack disconnect`. Only `slack send --project "My project"`, which manually sends a particular project's retained results, needs a project selector. Token input is hidden; scripts can explicitly use `--token-stdin --member U…`. Automatic notifications begin with results completed after connection; reconnecting or changing the recipient does not replay disconnected-period history. Existing credentials and delivery records survive the upgrade from project subscriptions. Slack settings never resume stopped research.

## Usage accounting and economy profile

Claude resume responses may report cumulative per-session `modelUsage`. BrainDance counts the increment for each invocation, retains the original provider aggregate, and displays fresh input/output separately from cache reads and cache creation. Historical corrections preserve original receipts, calls, scientific results and stopped/running state, with an audit trail. These are processing counters, not a subscription-limit percentage or a cash invoice.

New CLI/UI runs default to the economy profile: **four Haiku exploratory roles and two Sonnet roles** (problem discovery and new principles) in Balanced/Deep, or all six Haiku roles in Lite. Source excerpts and per-agent outputs are shorter; full evidence remains local. Advisory peer reviews use Haiku and the Chairman uses Sonnet. The original implementation executor and independent Reviewer keep their models and scientific workflow. `braindance auto economy` or `auto standard` changes a session's future profile without resuming it; `--standard` opts out when starting. Role-level and provider receipts remain available; no unmeasured token-saving percentage is claimed.

Each exploratory lens returns one compact JSON proposal. Its output ceiling leaves room to finish valid JSON; a definitively completed but invalid planning call gets a new retained attempt with more output headroom. Valid waves are reused, ambiguous incomplete calls remain held, and raw failures and actual usage stay recorded. Six real participant outputs and the original completion checks are still required. Resumed research receives the exact missing-stage feedback so it can continue the unfinished cycle.

## Broad discovery and independent preliminary studies

Normal timed CLI/UI starts use six independent exploratory agents by default: trends, problem discovery, cross-field principles, problem reframing, adversarial alternatives and falsifiable pilots. Routine trend/pilot roles use Haiku; the more demanding roles use the selected mode's generation model. They work from verified source excerpts in isolated contexts, without seeing one another's proposals. Their actual native Agent receipts are retained. The supplied broad-exploration prompt guides a five-idea synthesis and normally two shortlisted studies, with fresh prior-art checks before selection.

Each hypothesis records potential, provisional novelty, feasibility and falsifiability on a 0–100 scale with rationale. These are subjective judgments, not measured probabilities; unverified novelty remains explicitly provisional. The original independent Reviewer still checks novelty and actual experiments.

Each selected hypothesis becomes a durable task with a unique ID, workspace, native Claude continuation, source files, logs and report. **Every study invokes the unmodified original research-pipeline and its idea-discovery → experiment-bridge → auto-review-loop → summary workflow.** ARIS authors and debugs the real experiment implementation. BrainDance only supplies discovery advice, task routing, the existing execution broker and shared project conversation. A full extra advisory Council is reserved for promising measured results or when useful; negative preliminary studies still retain the original Reviewer and a report.

Authorized distinct GPUs permit concurrent studies; a single selected GPU stays exclusive and studies run sequentially. CPU studies respect the existing concurrency setting. No unselected GPU is used. Failed tasks resume their own workspace with backoff. Completing a study does not end the project: after the selected studies report, broad discovery explores new questions/fields until the same absolute deadline. The original internal review loop is never restarted by a timer. There is no new experiment-count, token or model-call cap.

`/tasks` or the Progress **가설 작업** button opens the keyboard-accessible study list, with View, Stop and Resume actions. `braindance tasks --project "My project"` lists independent tasks. `braindance task stop TASK_ID --project "My project"` stops one study and its active experiments; `task resume` queues its retained workspace. Project Stop/expiry cancels all studies. Progress shows task states and Ideas shows their scores. Project messages and human directions remain shared; execution receipts cannot be borrowed across studies. Reports retain per-task original Markdown plus readable project summaries and measured charts. Legacy bounded/single-run sessions remain supported.

## Fresh prior-art and novelty checks

Ideas are checked again after generation: the host searches the installed upstream arXiv and OpenAlex clients with alternative queries and no recency filter, retains raw responses/errors, and runs the original paper-existence verifier with `--no-cache`. Earlier verified flags do not substitute for this operation. The native executor loads the original `novelty-check` Skill and gets the original independent Reviewer comparison before registering a scouting candidate. Council separately re-searches its anonymous generated proposals before peer review and synthesis.

Existence, mechanism overlap and novelty are separate claims. Reviews name the closest verified prior work and the concrete technical difference. Missing or metadata-only evidence, unavailable sources and no-result searches leave novelty unverified; performance improvement alone cannot prove novelty. Nearby work alone does not invalidate an idea. Uncertain ideas can still be tested as exploratory pilots. All source diagnostics and full receipts remain local; reading reports still cite paper URLs only.

## Research advisor and readable reports

The main research executor loads `assets/research-advisor.md` as an additional Claude system prompt. It evaluates concrete problems, structural insights, fair experiments and novelty, while the original autonomous research Skills continue to execute. Confirmed observations, hypotheses and speculation remain distinct. The advisor's default discussion questions do not add human checkpoints to an authorized automatic run.

Reports use Korean Markdown sections for the problem, approach, exact retained source file and entry points, measured baseline/candidate results, limitations and next actions. Paper citations are plain URLs; full abstracts, bibliographic metadata, Council dumps and raw JSON stay in the local archive. The research database contains one page per project; dated report sections inside it contain real tables and charts immediately after the results. The Markdown report is attached; raw `results.json` remains local. Earlier published snapshots are preserved.

The automatic start dialog asks for total research hours once. An optional per-experiment cap lives in **고급 설정**; its separate dialog accepts minutes (`0` restores automatic allocation). `/limits` similarly shows only remaining research hours, with the cap under **고급 설정**; an existing custom cap is preserved when changing the deadline. For scripts: `braindance auto start --hours 8 --experiment-minutes 20`. Change the next experiment's allocation with `braindance limits --experiment-minutes 10`; it preserves the existing project end time. Changes apply to subsequent immutable experiment plans; work already running keeps its reviewed timeout. Legacy bounded/manual script allowances remain compatible and do not impose a second limit on deadline-only research. Count and token caps remain absent in timed mode.

## Project automatic mode

`braindance auto start --hours 8 --project "My project"` starts deadline-only autonomous research. The normal start wizard asks for a research folder and duration, plus the research style/model preset. There are **no model-call, token, dollar or experiment-count stop limits** in this mode. Account usage and all actual receipts remain recorded. Provider authentication and provider-side availability still apply.

The original main research Skills own discovery, hypothesis generation, implementation, experiments, interpretation and Reviewer-driven revisions. Council provides additional independent advice. A completed scientific batch is archived; the host starts a new research question or follow-up batch in the same project workspace and conversation. It does not restart the original internal review loop because a timer fired, borrow old completion receipts, or rerun unchanged successful pilots merely to fill time.

A hypothesis can conclude before experiments as **rejected** when the original research/idea/novelty Skills have actually run and the independent Reviewer explicitly agrees with evidence. Duplication or low-novelty rejection requires compared paper URLs; missing searches, a low score or transient tool failures alone are insufficient. The report preserves the reason, original Reviewer response and usage receipt, marks the hypothesis discarded, and states that no measurements were taken. Rejected tasks are terminal and are not retried as execution failures. Other hypotheses continue, and after the batch ends the project starts a new discovery cycle with its original deadline, device settings, conversation and usage intact. Existing experiments cannot be hidden behind this pre-experiment path; measured-study completion retains its normal requirements.

Failed experiments retain their exact source, logs and costs. The executor diagnoses code/import/environment problems and revises/reviews/reruns code automatically. Failed workers resume the same durable workspace with backoff. Valid negative results are recorded and exploration continues. Missing authentication or changed resources are reported without fabricating results or switching devices.

The absolute deadline includes research, model calls and execution. At expiry, the host stops new work, cancels in-flight project models/experiments and stores a final status report without an extra model call. Partial results and original logs remain available. Closing the CLI with `/exit` leaves the detached backend running; on macOS an idle-sleep assertion stays active during timed research. Restarted deadline-only sessions resume supervision with their original end time; offline time is not refunded. Stop cancels project work, while Pause prevents further automatic steps. Changing directions invalidates unexecuted older plans; running code remains immutable.

Advanced scripts can opt into the older `--bounded` policy with `--calls`, `--tokens` and `--cycles`. Only that policy enforces those numeric ceilings, uses cumulative process-runtime accounting and pauses after a backend restart. Standalone Council presets retain their own bounded defaults; when participating in a deadline-only project they use its shared usage ledger and deadline instead.

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
