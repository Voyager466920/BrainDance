# Lightweight BrainDance monitor

The monitor is a separate macOS user service. Every 60 seconds it starts a short, standard-library-only Python check, then exits. It can observe an unavailable BrainDance backend without relying on that backend's own worker loop.

## Install and inspect

```sh
braindance monitor install
braindance monitor status
braindance monitor check --no-notify
braindance monitor status --json
```

No project selection or new Slack token is required. The service uses the existing workspace and global personal Slack connection. Installing it does not start, stop or restart research. A manual `check --no-notify` updates local observations without sending a DM.

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
- The monitor opens research databases read-only. Its own checkpoints, incident history and delivery journal live in `~/Library/Application Support/BrainDance/monitor/`.
- Checks make zero model calls and no SSH requests. The monitor does not change budgets, control research or restart processes. Existing research repair loops remain in charge of recovery.

Stall alerts indicate a condition to inspect, not proof that a scientific result failed. Initial installation collects a baseline; a stall needs a full observation window. Suspended Macs do not perform checks until they run again.

## Remove the service

```sh
braindance monitor uninstall
```

This unloads the user LaunchAgent and removes its registration. Research, Slack credentials and monitor history are retained. The installed script, CA file and bounded service log remain in the private monitor folder for inspection or reinstallation.

[Back to README](../README.md)
