# Changelog

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
