# BrainDance

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

## Research through the experiment conversation

Open **실험 실행** (Experiments). The upper panel shows the actual current experiment or research stage and links to its live logs. The conversation below receives execution reports and analysis alongside your messages and real Codex replies.

- Ask about progress, evidence, results or blockers while research continues.
- Use **대화 · 의도에 맞게 반영** for natural conversation. Clear direction changes become instructions for the next step; explicit pause/stop requests control this project.
- **질문만 · 방향 유지** answers without changing the research direction.
- **방향 변경 · 다음 단계** records your instruction immediately and keeps the current experiment intact.
- **지금 중지하고 다시 준비** stops current work and prepares a replacement under the new direction.
- Choose the whole project or the selected hypothesis as the message scope. Enter sends; Shift+Enter adds a newline.

The conversation has a separate reply worker, so it can answer during a running research job. Replies use timestamped actual state and retained result reports; they do not claim live results that were not observed. Messages, action receipts and original model responses stay in your private workspace. Replies consume connected-account usage; active automatic sessions include them in their shared model budget. Reopening the app marks interrupted replies explicitly and does not replay model calls silently.

**실행 계획 · 코드 · 이전 실험** keeps immutable plans, source code and execution history available below the conversation. Manual code entry remains an advanced option.

## Project automatic mode

Each project tile has its own **자동모드** control, visible even when collapsed. Every new session starts paper discovery and hypothesis review at the project root, even when hypotheses already exist, then continues through experiment design, code authoring/review, self-tests, execution, analysis and a next-experiment decision.

Starting a session authorizes reviewed LLM-generated code on the selected project devices within the existing runtime budget; per-experiment human approval is unnecessary. Later iterations reuse the discovery evidence and actual result reports. Configure maximum experiments, model invocations, token admission budget, research mode and an optional target-side reference directory.

Pause allows current work to finish but starts no new automatic step. Stop cancels project work. Missing prerequisites, repeated identical code, consecutive failures or exhausted limits produce a report and stop. Changed directions invalidate unexecuted older plans; already-running code is never edited in place. Restarting the app pauses automatic sessions for explicit resume. Token limits are conservative admission estimates, not provider hard spending caps; in-flight usage can exceed estimates. Models cannot expand devices, budgets or permissions through chat.

## Local and SSH experiments

Settings shows the current CLI authentication, reported subscription plan and available quota windows. Unknown plans or unavailable usage are labelled explicitly. Settings also supports SSH profiles, connection checks and GPU discovery. Existing keys, SSH agent and host aliases are used; private connection settings stay outside the repository.

Remote execution requires `python3`; NVIDIA discovery additionally requires `nvidia-smi`. Choose an installed Python environment for ML dependencies. The built-in runtime supports standard-library code. The app does not install remote packages or download models implicitly.

Experiments receive `BRAINDANCE_DEVICE`, `CUDA_VISIBLE_DEVICES`, `BRAINDANCE_GPU_IDS`, `BRAINDANCE_METRICS_PATH` and `BRAINDANCE_ARTIFACT_DIR`. Write actual measured JSON metrics such as `{"baseline":{"accuracy":0.5},"candidate":{"accuracy":0.7}}` and save artifacts under the provided directory. The runner preserves raw logs, exit status, metrics and artifact receipts. Observed differences do not establish statistical significance. The supplied synthetic CPU example verifies the execution infrastructure; it is not a paper reproduction or VLA validation.

## Run from source

Use Python 3.12 or later and the authenticated CLIs. Node.js is optional for the browser-script tests.

```sh
git clone https://github.com/Voyager466920/BrainDance.git
cd BrainDance
python3 braindance.py --db "$HOME/Library/Application Support/BrainDance/tree.sqlite3" --port 8766
```

Stop the native app before opening the same workspace from source. To use a different engine checkout, set `BRAINDANCE_ENGINE_DIR` to its absolute path before launching the backend. Legacy engine settings remain supported.

Build the native app on macOS:

```sh
python3 -m venv .venv
.venv/bin/pip install -r desktop/requirements-build.txt
.venv/bin/python desktop/build.py
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
