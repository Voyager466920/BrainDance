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
5. Set the concurrency and time budget, then click **프로젝트 만들기** (Create project).

Use the gear icon to open settings. The **SSH 추가** (Add SSH) tab lets you save and test a remote connection. You can also open it from the new-project form without losing your draft.

Settings opens on **계정 · 플랜** (Accounts & plans), showing the subscription reported by the locally signed-in Codex and Claude accounts, authentication state and available quota windows. After changing accounts in the CLIs, click **계정 정보 새로고침** (Refresh account information). Unknown plans are shown as unavailable; API authentication is distinguished from a subscription. Claude Max 5×/20× is displayed only when matching plan metadata identifies that tier. Usage-query failures do not hide an already verified plan, and manual refresh respects provider rate-limit backoff. No model inference is started to read this information. Account emails, identifiers and credentials are not sent to the interface or saved with project data.

Click a project title to collapse or expand its nodes. The trash icon on the right moves the project to Trash, where it can be restored.

Open **휴지통** (Trash) and choose **영구 삭제** (Delete permanently) to remove a project after reviewing its name, record counts and local file size. This removes its database records, unshared imported Council conversations, project resource assignment, and dedicated local experiment logs/artifacts. SQLite is compacted to reclaim free pages. Exclusive Council outputs are removed only when they are under the workspace's managed `council-runs/` directory. Shared runs, arbitrary external folders, model/dataset caches, backups, SSH profiles/keys, and files on remote servers remain intact. Permanent deletion cannot be restored. If file cleanup fails, Trash retains a **정리 재시도** (Retry cleanup) entry, including after restarting the app. Queued, running or finishing experiments must stop before permanent deletion.

**Creating a project does not start an experiment.** Open a node's **실험 실행** (Run experiments) tab to save Python code, review its exact code/device/time limit, and approve execution. BrainDance now supervises local and SSH runs and enforces project concurrency and time budgets. Device locks coordinate BrainDance's own jobs; they do not reserve a GPU against other software.

### Run an experiment

1. Select an active research node and open **실험 실행**.
2. Enter Python code or load **CPU 검증 예제** (CPU verification example). Set a timeout, primary metric, and whether a larger or smaller value is better.
3. For ML libraries, expand the advanced options and select the Python executable of your prepared environment, such as `/path/to/venv/bin/python`. The bundled interpreter includes the standard library, not PyTorch or model dependencies. SSH paths refer to the remote host.
4. Save the plan, inspect the stored code and resources, check the consent box, then choose **승인하고 실행** (Approve and run).
5. Open the run to inspect live stdout/stderr, exit status, metrics, and downloadable artifacts. Use **중지** (Stop) to terminate its process group.

To queue approved work automatically, enable **승인된 실험 자동 실행** in project settings and use **승인 후 자동 대기** on each reviewed plan. Each approval permits one run. Unapproved ideas and Council hypotheses do not execute automatically. Failed or interrupted work is not automatically retried.

Python scripts receive `BRAINDANCE_DEVICE` (`cpu`, `mps`, or `cuda`), `BRAINDANCE_METRICS_PATH`, and `BRAINDANCE_ARTIFACT_DIR`. Write a JSON object to the metrics path and output files under the artifact directory. For comparison, use `{"baseline":{"accuracy":0.5},"candidate":{"accuracy":0.7}}`. BrainDance records the observed difference; it does not establish statistical significance. See [execution details](.claude/skills/aris-research-council/references/experiments.md) for the complete contract and limits.

The supplied CPU example trains a small classifier on synthetic data to verify execution. It is not a reproduction of a paper or a validation of a research hypothesis. Automatic LLM code generation and autoresearch are not included.

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

The Council runs three Claude specialists and an independent Codex participant through hypothesis generation and anonymous cross-review, followed by a separate Claude Chairman synthesis. Council runs consume usage from connected accounts. They are invoked separately through the Skill or runner; opening the app or creating a project does not invoke models.

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
- Explicitly approved Python execution, an automatic approved-work queue, timeouts, cancellation, live logs, metrics comparison, and artifact collection.
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
