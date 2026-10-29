# Lightweight BrainDance monitor

The monitor is a separate macOS user service. Every 60 seconds it starts a short, standard-library-only Python check, then exits. It can observe an unavailable BrainDance backend without relying on that backend's own worker loop.

## Install and inspect

```sh
braindance monitor install
braindance monitor status
braindance monitor check --no-notify
braindance monitor status --json
```

No project selection or new Slack token is required. The service uses the existing workspace and global personal Slack connection. Installing it enables guarded automatic recovery for already authorized research. It does not start a new project, resume a user-paused project or extend any limit. A manual `check --no-notify` updates local observations without sending a DM.

For a separate local workspace, pass its database and backend address:

```sh
braindance monitor install --db /absolute/path/tree.sqlite3 --server http://127.0.0.1:8770
```

Only loopback HTTP addresses are accepted. `monitor status` reads monitor records without starting the backend or creating a research database. The service uses `/usr/bin/python3` with isolated mode and a private CA bundle copied at installation, so it does not depend on an open CLI session or a temporary packaged-app directory.

## What it checks

| Condition | Detection |
| --- | --- |
| Backend unavailable during active research | Three consecutive unsuccessful health checks, including workspace identity. |
| Suspected stalled research | Fifteen minutes without a meaningful stage or completed tool-result change. Worker heartbeats and growing `tool_progress` logs do not count as scientific/workflow progress. |
| Repeated errors | Three distinct similar error events within 30 minutes, with a recent occurrence. Error categories are retained without copying model/source text into the monitor. |
| Experiment overdue | A running experiment record exceeds its reviewed timeout plus a two-minute cleanup allowance. |

An experiment still inside its reviewed runtime can run quietly without being labelled stalled. Paused, stopped, completed, trashed and expired research sessions are excluded from active stall monitoring. GPU execution is observed through BrainDance's run records; the monitor does not poll SSH or GPU hardware.

## Notifications and safety

- Normal operation is quiet. A newly detected condition sends one message to the registered personal Slack DM, using the existing notification setting.
- A subsequent progress update or restored backend response can send a condition-cleared message. A user stop/pause does not get described as a successful recovery.
- Duplicate incidents are suppressed. Known Slack HTTP 429 responses wait for their retry interval; ambiguous sends are retained as uncertain and are not replayed automatically.
- Muted or disconnected Slack connections do not receive queued old alerts. Changing the recipient cancels alerts queued for the old destination.
- The independent monitor opens research databases read-only. Recovery requests use the backend’s origin/CSRF-protected local API. Its own checkpoints, incident history and delivery journal live in `~/Library/Application Support/BrainDance/monitor/`.
- Routine checks make zero model calls and no SSH requests. A repeated failure can queue one read-only Codex diagnosis using the existing shared project allowance. ARIS receives the concrete diagnosis in its original workspace and owns code/input repair, review and actual experiments.
- Recovery retains the same session, conversation, selected devices, deadline and charged usage. Pause/stop, authentication and account allowance guards remain authoritative. Valid GPU experiments are not interrupted for diagnosis; overdue runs use the existing cancellation path.
- The same cause waits five minutes between repair attempts, with at most three diagnosis attempts per 30 minutes. A concrete host traceback can launch a detached source-repair worker. Its patch is limited to the failing BrainDance function in a registered source snapshot; original ARIS and resource, allowance, credential and review-gate controls are excluded. The worker replays supported concrete failures, runs the unchanged full regression suite, builds and checks the CLI, then waits for idle research before replacing the backend. A failed check may request one revised patch with its retained test output, under the same deadline and allowance. Failed candidates never replace the working runtime; failed startup restores the previous immutable image. Actual resumed tool success is required before confirmation.
- Only the registered, hash-checked immutable backend can be restarted after three failed health checks. Graceful shutdown owns worker cleanup; an active experiment remains protected until its reviewed timeout and cleanup grace expire. Unrelated processes and occupied ports are refused.
- A queued restart or proposed fix is not confirmed recovery. The backend requires a real success receipt for the previously failing operation; discovery requires the actual six-agent exploration receipt.

Stall alerts indicate a condition to inspect, not proof that a scientific result failed. Suspected stalls alone do not cancel a slow native call; its bounded operation allowance is checked before intervention. Initial installation collects a baseline; a stall needs a full observation window. Suspended Macs do not perform checks until they run again.

## Automatic recovery controls

```sh
braindance monitor repair-on
braindance monitor repair-off
```

`repair-off` keeps alerts enabled. `--no-notify` only suppresses Slack delivery; it does not disable enabled recovery. Repair diagnosis requests, raw MCP responses, usage and confirmation records are retained under the private monitor directory and `watchdog_repairs` table. A missing build environment, errors in protected controls, unsuccessful patches/tests, missing permissions or unavailable credentials remain explicit attention cases. Detached repair process exits are detected; they cannot hold a session indefinitely. Research completion and hypothesis support remain separate from infrastructure recovery.

## Program source repair

A locally built standalone CLI automatically registers a private source snapshot and the Python build environment when `--install-cli` runs. No open Codex chat is required. Normal monitoring remains zero-model; diagnosis and patch generation happen only for a concrete failure and are charged to the same research allowance. Repair never extends the deadline, resumes a user-stopped session or reassigns GPUs.

For a downloaded CLI with a separate local source checkout, register its build environment once:

```sh
python3 -m venv .venv
.venv/bin/pip install -r desktop/requirements-build.txt
braindance monitor repair-source --source "$PWD" --python "$PWD/.venv/bin/python"
```

Use the matching BrainDance source release. Sources, proposed edits, raw model responses, test/build/replay logs and the previous binary are retained under `monitor/`. Automatic repairs are local; they do not publish code to GitHub or modify the original checkout. The worker can survive a backend restart and continues the same project tasks after successful installation. It is not a second research planner and cannot declare a scientific finding successful.

## Remove the service

```sh
braindance monitor uninstall
```

This unloads the user LaunchAgent and removes its registration. Research, Slack credentials and monitor history are retained. The installed script, CA file and bounded service log remain in the private monitor folder for inspection or reinstallation.

[Back to README](../README.md)
