# Approved experiment execution

Council outputs remain research proposals. Prepare an executable Python plan separately, including its dependencies, dataset, baseline, evaluation split, primary metric, device and maximum duration. Never report an experiment as executed without a completion receipt and actual outputs. The CPU template is synthetic infrastructure verification, not research evidence.

## Workflow and approval

Use the node's **실험 실행** tab. Saving creates an immutable plan containing Python source, interpreter, working directory, argument array, target profile, devices, timeout and metric. Inspect it and explicitly approve its digest. Changing the code requires a new plan; changing resource or budget settings invalidates existing plans. Each approval can launch exactly one run, and duplicate dispatch requests return the same run. A new attempt requires new approval.

**승인하고 실행** queues the plan immediately. **승인 후 자동 대기** leaves it for the automatic queue, which runs only while that project's auto mode and the backend are active. No unapproved plan executes. Auto mode does not generate code, extend budgets, retry failures, or turn Council ideas into jobs. Inactive/discarded nodes and trashed projects cannot start new work. Execution records remain in the research journal.

## Runtime and dependency contract

- `builtin` uses the source server's Python or the app's bundled standard-library Python. Choose an existing virtual-environment executable for third-party ML libraries. Dependencies are not installed automatically.
- An interpreter is one executable path/name, not a shell command. Arguments are a JSON array of strings. `cwd` is optional; an empty value uses the isolated run directory. Remote paths refer to the SSH host.
- `BRAINDANCE_DEVICE` is `cpu`, `mps` or `cuda`; the script must choose a compatible framework device. `CUDA_VISIBLE_DEVICES` contains the chosen NVIDIA UUIDs for CUDA and is empty otherwise. `BRAINDANCE_GPU_IDS` records the selected identifiers. These settings are not hardware isolation.
- `BRAINDANCE_RUN_DIR` is the run directory. Write a JSON object to `BRAINDANCE_METRICS_PATH`, and files under `BRAINDANCE_ARTIFACT_DIR`. Baseline/candidate dictionaries using the selected metric produce an observed delta and ranking. A top-level numeric metric produces a measurement. Missing or invalid metrics are explicitly flagged, even after exit code zero. No significance or causal claim is generated.
- The child receives a minimal environment without provider API keys. Execution still has the local/SSH user's file permissions; this is process supervision, not a security sandbox.

SSH uses existing noninteractive authentication, strict host-key verification and a remote `python3` supervisor. The same worker source is sent over SSH; approved code and settings travel on stdin. Target-side files are retained at `~/.local/share/braindance/runs/<run-id>/`. Local files are under the database directory's `experiment-runs/<run-id>/`.

## Limits and recovery

The queue permits at most four simultaneous jobs globally and the configured concurrency per project. Selected device IDs cannot overlap between this executor's concurrent jobs on the same target. This is not an exclusive GPU reservation against other software.

Time budget is cumulative process runtime. Queued/running jobs reserve their full timeout; completed jobs charge measured duration. Interrupted jobs conservatively charge their timeout. Saving project resources with **적용 · 예산 시작** begins a new budget period. Existing queued work from an older period is blocked. Runtime is not a financial or cloud billing limit. Preflight discovery verifies the selected target/device before starting.

Timeout, Stop, backend shutdown and a lost supervisor connection terminate the child process group (TERM followed by KILL if needed). Quitting cancels queued jobs. A missing completion receipt becomes `interrupted` and is not retried automatically. Restart recovery does not claim a remote job succeeded. Applications that intentionally detach processes can escape ordinary process-group supervision.

Raw stdout/stderr are retained without text compression, up to 8 MiB per stream. Exceeding the limit stops the job and explicitly records truncation. The UI displays a 32 KiB tail; downloadable logs contain the retained bytes. Original source and code/settings hashes are preserved in receipts.

Metrics JSON is limited to 1 MiB. Artifact transfer is limited to 2 MiB per file and 20 MiB per run; up to 1,000 artifact entries are considered. Oversized originals remain on the execution target, with warnings. Symlinks and paths outside the run directory are excluded. Transferred files have verified SHA-256 hashes. These limits are deliberate and must not be described as lossless unlimited collection.

## Validation scope

Automated tests run real CPU subprocesses, automatic approved dispatch, HTTP endpoints, live logs, budget/concurrency limits, cancellation, timeouts, restarts and malformed/failing output. The SSH protocol is exercised through a local transport fixture. Tests do not demonstrate connectivity to a real remote host, actual GPU training, or scientific validity of Council hypotheses. Validate those separately with an explicitly approved plan and budget.
