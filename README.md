# BrainDance

A local research workspace for exploring ARIS research plans, organizing hypothesis trees, and keeping evidence, Council reviews, and research records together.

The interface and generated research content are currently Korean-first. Installation and setup instructions below are in English.

## Install the Mac app

### Requirements

- An Apple Silicon Mac (M1 or newer).
- macOS 13 or later.
- No separate Python installation is required for the packaged app.

### Installation

1. Download [BrainDance for Apple Silicon](https://github.com/Voyager466920/BrainDance/releases/latest/download/BrainDance-macOS-arm64.zip), or select a version from [Releases](https://github.com/Voyager466920/BrainDance/releases).
2. Extract `BrainDance-macOS-arm64.zip`.
3. Drag `BrainDance.app` into your **Applications** folder.
4. Open **BrainDance** from Applications or Spotlight.

Release builds are ad-hoc signed and are **not notarized by Apple**. You can also build the app from source using the instructions below.

The app uses a native AppKit window with WKWebView and includes its Python backend and CA certificate bundle. Claude Code, Codex CLI, and SSH authentication are separate prerequisites only for the features that use them.

### Create your first project

1. Click **＋ 새 프로젝트** (New project) in the sidebar.
2. Enter a project name and research goal.
3. Choose a local or saved SSH execution environment.
4. Click **장치 조회** (Discover devices), then select CPU or one or more GPUs.
5. Set the concurrency and time budget, then click **만들고 연구 시작** (Create and start research), or disable the research-start option to save only.

The **만들고 연구 시작** (Create and start research) option is enabled by default and clearly indicates Claude/Codex usage. Disable it to save the project without starting model work. For an existing project, click **연구 시작** (Start research), review Lite/Balanced/Deep and the limits, then confirm. **Balanced** is the default.

The app now runs the installed official ARIS `research-lit` Skill, the official paper-identity verifier, and the existing four-participant Council through experiment design, followed by Codex code authoring and Claude code review. A project badge and stage panel show actual progress: literature discovery, identity checks, hypothesis generation, anonymous cross-review, Chairman synthesis, and design persistence. **진행 기록** (Progress log) shows stage events and downloadable evidence, usage receipts and reports. The green node indicator describes node eligibility; a separate **진행 중** badge indicates running research. Research requires both authenticated CLIs and the official ARIS checkout at `~/aris_repo` (or `ARIS_REPO`). It uses the selected account quotas. Manual research stops for code approval; project automatic mode can continue into experiments on the selected device.

Each research launch runs one bounded Council. You can stop it from the project panel. Failures and interruptions retain partial artifacts and explicit states; they do not silently retry model calls. Research runs while the app/backend is open. Restarting marks unfinished jobs as interrupted. Starting again creates a new run and can consume usage again. At most one research job runs in a workspace at a time. Manual executable experiments require code/device/time approval. A started project automatic session authorizes its reviewed LLM plans within the configured limits.

For the same project and goal, saved verified literature is reused by default to avoid duplicate discovery calls. Uncheck **동일 목표의 저장된 논문 근거 재사용** to search again. A new Council still consumes usage. The execution-history selector retains previous failed/stopped runs, and reused-literature receipts link to their source run.

Use the gear icon to open settings. The **SSH 추가** (Add SSH) tab lets you save and test a remote connection. You can also open it from the new-project form without losing your draft.

Settings opens on **계정 · 플랜** (Accounts & plans), showing the subscription reported by the locally signed-in Codex and Claude accounts, authentication state and available quota windows. After changing accounts in the CLIs, click **계정 정보 새로고침** (Refresh account information). Unknown plans are shown as unavailable; API authentication is distinguished from a subscription. Claude Max 5×/20× is displayed only when matching plan metadata identifies that tier. Usage-query failures do not hide an already verified plan, and manual refresh respects provider rate-limit backoff. No model inference is started to read this information. Account emails, identifiers and credentials are not sent to the interface or saved with project data.

Click a project title to collapse or expand its nodes. The trash icon on the right moves the project to Trash, where it can be restored.

Open **휴지통** (Trash) and choose **영구 삭제** (Delete permanently) to remove a project after reviewing its name, record counts and local file size. This removes its database records, unshared imported Council conversations, project resource assignment, and dedicated local experiment logs/artifacts. SQLite is compacted to reclaim free pages. Exclusive Council outputs are removed only when they are under the workspace's managed `council-runs/` directory. Shared runs, arbitrary external folders, model/dataset caches, backups, SSH profiles/keys, and files on remote servers remain intact. Permanent deletion cannot be restored. If file cleanup fails, Trash retains a **정리 재시도** (Retry cleanup) entry, including after restarting the app. Queued, running or finishing experiments must stop before permanent deletion.

**Creating a project can start research planning. Enable project automatic mode separately to authorize execution without repeated code approvals.** Open a node's **실험 실행** (Run experiments) tab to save Python code, review its exact code/device/time limit, and approve execution. BrainDance supervises local and SSH runs and enforces project concurrency and time budgets. Device locks coordinate BrainDance's own jobs; they do not reserve a GPU against other software.

### Automatic mode and human direction

Click **자동모드** on each project tile to choose the maximum experiment count, model invocation count, token admission budget, research mode and optional target-side reference folder. Starting the session authorizes reviewed LLM-generated experiments on the project's selected devices and existing remaining time budget; individual code approvals are no longer required. Each new session starts official ARIS discovery and Council from the project root even when hypotheses already exist, then loops through code authoring, review, self-tests, actual execution, result analysis and the next evidence-based comparison. After discovery completes, later experiment iterations reuse its evidence and actual result reports. Project modes are independent; a tile shows its current stage even when collapsed. Models do not extend limits. Arbitrary manual code is not auto-approved.

Both **연구 개요** and **실험 실행** provide **방향 수정 · LLM에 지시**. Choose **다음 단계에 반영** to preserve the current experiment, or **지금 중지하고 다시 준비** to cancel it and generate a replacement. The instruction history shows when each direction reached an LLM job. Existing code is never edited mid-run. Older unexecuted LLM plans become stale when directions change. Current experiment titles, device/time limits, live logs and recent result reports appear alongside these controls.

Pause allows already-running work to finish and starts no new automatic step. Stop cancels project work. Missing prerequisites, repeated identical code, consecutive failures or exhausted limits stop with a reason. Reports distinguish observed metrics from interpretation. The token budget is a conservative admission estimate, not a provider hard spending cap; in-flight usage can exceed estimates. Model calls and reservations are shared across all stages and survive restarts. Reopening the app pauses automatic sessions; Resume continues within their remaining limits.

### LLM-authored experiments

After Council, BrainDance selects a high-priority active hypothesis, reads the chosen target's Python/package inventory and an optional reference directory, and asks Codex to produce runnable Python with embedded self-tests. Claude reviews that exact code against the hypothesis and actual target. Syntax and entrypoint checks run before registration; generated code executes only under a manual approval or a user-enabled automatic session. A failed static/review check permits at most one bounded author repair. Missing models, datasets, interfaces or required hardware produce an explicit prerequisite list, not a fake ready-to-run plan or synthetic replacement.

For existing hypotheses, select **LLM으로 실험 준비** (Prepare experiment with LLM). You can enter the path to existing experiments on the selected target. The bounded read-only inventory does not install packages, train models or read credential directories. Review the generated plan's purpose, environment, dependencies and limit, then choose **승인하고 실행**. You do not need to write Python. The manual code editor remains an advanced option.

Approval runs the generated self-tests first and then the experiment, within the same device/time limit. A passing syntax check or review is not a runtime test result. The runner records the actual self-test marker, exit code, metrics and artifacts. Completion automatically queues a separate real Codex analysis using actual receipts and log tails; its findings are saved in the research journal. It cannot fabricate successful metrics from a failed run. Analysis consumes connected-account usage and is indicated on LLM-generated plans. Cancelled/interrupted experiments do not silently start new analysis; failed/completed attempts are not endlessly retried. Changed code receives a new exact-digest receipt, manually approved or authorized by the active automatic session.

### Run an experiment

1. Select an active research node and open **실험 실행**.
2. Enter Python code or load **CPU 검증 예제** (CPU verification example). Set a timeout, primary metric, and whether a larger or smaller value is better.
3. For ML libraries, expand the advanced options and select the Python executable of your prepared environment, such as `/path/to/venv/bin/python`. The bundled interpreter includes the standard library, not PyTorch or model dependencies. SSH paths refer to the remote host.
4. Save the plan, inspect the stored code and resources, check the consent box, then choose **승인하고 실행** (Approve and run).
5. Open the run to inspect live stdout/stderr, exit status, metrics, and downloadable artifacts. Use **중지** (Stop) to terminate its process group.

To queue approved work automatically, enable **승인된 실험 자동 실행** in project settings and use **승인 후 자동 대기** on each reviewed plan. Each approval permits one run. Unapproved ideas and Council hypotheses do not execute automatically. Failed or interrupted work is not automatically retried.

Python scripts receive `BRAINDANCE_DEVICE` (`cpu`, `mps`, or `cuda`), `BRAINDANCE_METRICS_PATH`, and `BRAINDANCE_ARTIFACT_DIR`. Write a JSON object to the metrics path and output files under the artifact directory. For comparison, use `{"baseline":{"accuracy":0.5},"candidate":{"accuracy":0.7}}`. BrainDance records the observed difference; it does not establish statistical significance. See [execution details](.claude/skills/aris-research-council/references/experiments.md) for the complete contract and limits.

The supplied CPU example trains a small classifier on synthetic data to verify execution. It is not a reproduction of a paper or a validation of a research hypothesis. LLM code generation and a bounded, user-steerable automatic research loop are included.

### Local data

The Mac app stores its workspace in:

```text
~/Library/Application Support/BrainDance/
```

Research databases, credentials, and SSH keys are not included in the app or release archive. Back up this directory to preserve your app workspace.

The default local address is `http://127.0.0.1:8766/`. If another service occupies that port, the backend uses an available loopback port. If a matching-version BrainDance server is already running on port 8766, the app connects to that workspace. Close older servers before opening an updated app. Quitting an app-owned backend stops its active experiments and cancels queued work. Automatic queues run while the backend is open; this is not a background service.

## Run the browser version from source

Requires **Python 3.9 or later**, Git, and a modern browser. The Viewer uses only the Python standard library.

```sh
git clone https://github.com/Voyager466920/BrainDance.git
cd BrainDance

python3 .claude/skills/aris-research-council/scripts/viewer.py \
  --db .aris/council/tree.sqlite3 --port 8766
```

Open <http://127.0.0.1:8766/>. A fresh checkout starts with an empty workspace.

This command stores data under `.aris/council/` in the checkout. To use the Mac app's existing workspace instead, stop the app and run:

```sh
python3 .claude/skills/aris-research-council/scripts/viewer.py \
  --db "$HOME/Library/Application Support/BrainDance/tree.sqlite3" --port 8766
```

Keep the Viewer on loopback; it is not intended for public network hosting.

## Set up SSH and GPU discovery

- BrainDance uses your existing SSH config, keys, and SSH agent. Passwords and private-key contents are not stored in connection profiles.
- A remote host needs `python3`. NVIDIA GPU discovery also needs `nvidia-smi` on that host.
- SSH checks are noninteractive and require a trusted host key. Unknown or changed host keys are not automatically accepted.
- Local Apple GPU discovery reports Metal hardware. Model and framework compatibility must be checked separately before an experiment.
- Selecting a GPU saves the intended device for the project; it does not reserve it or prevent other processes from using it.

## Set up the Research Council

Actual Council runs require:

1. The official [ARIS repository](https://github.com/wanshuiyin/Auto-claude-code-research-in-sleep), installed using its own instructions.
2. Installed and authenticated Claude Code and Codex CLI.
3. An ARIS literature review and saved paper-evidence records.

BrainDance reuses ARIS's official `codex-exec` MCP bridge. Its project-local Skill is at [.claude/skills/aris-research-council/SKILL.md](.claude/skills/aris-research-council/SKILL.md).

The Council runs three Claude specialists and an independent Codex participant through hypothesis generation and anonymous cross-review, followed by a separate Claude Chairman synthesis. Council runs consume usage from connected accounts. Use the app's explicit research-start controls or the Skill/runner. Opening the app alone never starts research. The literature stage copies the unmodified installed ARIS Skill and its references into a private session plugin, runs it with command execution/delegation disabled, then invokes the upstream verifier on the host. Original abstracts are fetched with ARIS's helper when available; source excerpts/summaries and unavailable-source limitations remain labelled. This host adaptation is not stock ARIS. Code preparation can inspect a reference directory you explicitly enter on the selected local/SSH target; it does not infer permission to scan arbitrary folders from a goal.

See the [protocol](.claude/skills/aris-research-council/references/protocol.md) for commands, modes, budgets, and recovery behavior; [optimization notes](.claude/skills/aris-research-council/references/optimization.md) for token controls; and [provenance](.claude/skills/aris-research-council/references/provenance.md) for reused components and license notices.

To display a Council run in the Mac app, pass the same database path to the runner with `--db "$HOME/Library/Application Support/BrainDance/tree.sqlite3"`.

## Build the Mac app from source

Requires macOS, Xcode Command Line Tools, Git, and `uv`. Run the following from a new checkout:

```sh
git clone https://github.com/Voyager466920/BrainDance.git
cd BrainDance

uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python -r desktop/requirements-build.txt
.venv/bin/python desktop/build.py
```

The build creates:

```text
dist/BrainDance.app
dist/BrainDance-macOS-<architecture>.zip
```

The architecture follows the build machine. The published `arm64` archive is for Apple Silicon. Builds include the backend runtime and third-party license notices, but do not copy research data into the app bundle.

## Features

- Persistent projects and research-problem → question → hypothesis trees.
- Paper evidence, ideas, proposed experiments, actual-result records, analysis, and notes.
- Council evaluations and retained participant requests and responses.
- Local and SSH device discovery with per-project CPU/GPU and budget settings.
- Manual or project-authorized automatic Python execution, human direction changes, iterative result reports, timeouts, cancellation, live logs, metrics comparison, and artifact collection.
- Project Trash and restore, with active and discarded node styling.
- GPT (Codex) and Claude authentication and account-quota indicators, where available.
- A dark interface with restrained yellow and cyan accents.

## Privacy and authentication

Private research inputs, databases, results, logs, credentials, and SSH settings are not distributed with this repository. Runtime directories such as `.aris/` and `council/` are excluded from Git. Do not commit private workspace data to a public repository.

The Viewer binds to loopback and checks Host, Origin, and CSRF tokens. Account-quota checks use existing CLI authentication. On macOS, Claude subscription usage is queried using existing OAuth credentials in Keychain. Tokens and account identifiers are not returned to the UI or application logs.

An authentication indicator is not proof that an inference request will succeed. Usage that cannot be queried is shown as unavailable or rate-limited, rather than as zero.

Approved experiment code runs with the current local or SSH user's permissions. Process supervision is not an OS security sandbox. Provider API keys are not inherited by child processes, but scripts can access files available to that user. Review code before approving it. Original code, execution receipts, and logs are stored in the private workspace under `experiment-runs/`; SSH runs also retain originals under `~/.local/share/braindance/runs/` on the target.

## Tests

```sh
python3 -m unittest discover \
  -s .claude/skills/aris-research-council/scripts -p 'test_*.py'
```

Tests use temporary databases, loopback HTTP, and synthetic inputs. They do not require personal research data, model calls, or GPU experiments. Node.js is used for JavaScript rendering checks when installed.

## License

MIT. Notices for the reused LLM Council design are retained in the provenance document. Official ARIS, Claude Code, and Codex CLI remain separate projects and services with their own terms.
