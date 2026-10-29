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
- The same cause waits five minutes between repair attempts, with at most three diagnosis attempts per 30 minutes. A diagnosis requiring a host source patch is held and reported instead of repeatedly launching the same failed research. The adviser cannot edit BrainDance source, credentials or budgets.
- Only the registered, hash-checked immutable backend can be restarted after three failed health checks. Graceful shutdown owns worker cleanup; an active experiment remains protected until its reviewed timeout and cleanup grace expire. Unrelated processes and occupied ports are refused.
- A queued restart or proposed fix is not confirmed recovery. The backend requires a real success receipt for the previously failing operation; discovery requires the actual six-agent exploration receipt.

Stall alerts indicate a condition to inspect, not proof that a scientific result failed. Suspected stalls alone do not cancel a slow native call; its bounded operation allowance is checked before intervention. Initial installation collects a baseline; a stall needs a full observation window. Suspended Macs do not perform checks until they run again.

## Automatic recovery controls

```sh
braindance monitor repair-on
braindance monitor repair-off
```

`repair-off` keeps alerts enabled. `--no-notify` only suppresses Slack delivery; it does not disable enabled recovery. Repair diagnosis requests, raw MCP responses, usage and confirmation records are retained under the private monitor directory and `watchdog_repairs` table. Unknown host bugs, missing permissions and unavailable credentials may still require attention. Research completion and hypothesis support remain separate from infrastructure recovery.

## Remove the service

```sh
braindance monitor uninstall
```

This unloads the user LaunchAgent and removes its registration. Research, Slack credentials and monitor history are retained. The installed script, CA file and bounded service log remain in the private monitor folder for inspection or reinstallation.

[Back to README](../README.md)
