# Slack setup and project conversations

BrainDance can send research reports to your personal Slack DM and receive instructions there. One connection covers all projects. Only the registered member in the registered workspace and bot DM can issue commands.

The Mac must stay awake with the local BrainDance backend running. Closing the terminal view does not cancel backend work. Socket Mode opens an outbound connection; no public HTTP event endpoint is required.

## Connect Slack

Open [Your Apps](https://api.slack.com/apps) and choose the same BrainDance app for all steps. The supplied [app manifest](../.claude/skills/aris-research-council/assets/slack-app-manifest.json) includes the bot scopes, event and App Home settings. App-level tokens are generated separately.

### 1. Connect result notifications

1. Under **OAuth & Permissions → Bot Token Scopes**, keep `chat:write` and `im:write`. Add `im:history` for incoming DM commands.
2. Install or reinstall the app in your workspace and copy its **Bot User OAuth Token** beginning with `xoxb-`.
3. In Slack, open your own profile and use **Copy member ID**. Use your member ID, not the bot's ID.
4. In BrainDance, open `/slack`, enter the member ID and bot token in the hidden field, then choose **연결 저장**. No project selection is needed.

Saving validates authentication and opens the bot DM; it does not send a test message. Choose **테스트 DM** if you want an explicit test. If reinstalling changes the bot token, update this connection before setting up incoming commands.

### 2. Enable incoming instructions

1. Open **Settings → Socket Mode** and enable **Enable Socket Mode**.
2. Under **Basic Information → App-Level Tokens → Generate Token and Scopes**, create a token named `braindance` with `connections:write`. Copy the generated `xapp-` token.
3. Under **Event Subscriptions**, turn on **Enable Events**. Expand **Subscribe to bot events**, choose **Add Bot User Event**, add `message.im`, and select **Save Changes**. Reinstall if Slack requests it.
4. Under **App Home → Show Tabs → Messages Tab**, enable the tab and check **Allow users to send Slash commands and messages from the messages tab**.
5. In BrainDance, open `/slack remote` or `/slack → DM 지시`. Paste the `xapp-` token in the hidden field, enable **본인 개인 DM 지시 수신**, and save.

These are different tokens:

| Token | Slack location | BrainDance location | Purpose |
| --- | --- | --- | --- |
| `xoxb-` | OAuth & Permissions | `/slack` | Authenticate the bot and send replies/reports. |
| `xapp-` | Basic Information → App-Level Tokens | `/slack remote` | Establish the Socket Mode event connection. |

Never send either token in Slack messages, research prompts or Git. Hidden terminal setup is also available with `braindance slack setup` and `braindance slack remote-setup`; neither command requires a token argument.

See Slack's official [Socket Mode guide](https://docs.slack.dev/apis/events-api/using-socket-mode/), [DM event reference](https://docs.slack.dev/reference/events/message.im/) and [Python SDK setup](https://docs.slack.dev/tools/python-slack-sdk/socket-mode/).

## Choose a project and talk

Send each line as a separate message in the app's personal DM:

```text
프로젝트 목록
프로젝트 선택 My research
상태
```

Use the exact project name or an unambiguous ID prefix of at least six characters from the list. **Replies are posted in the thread under your command**, so open that thread to read the answer and continue the conversation.

- A new top-level DM uses the latest selected project.
- A thread stays bound to its original project even after you select another one. Select a different project in a new top-level DM.
- Replying under a BrainDance result report targets that report's project directly.
- CLI messages, Slack instructions, research records and the Codex conversation belong to the same project. Slack threads do not create separate research sessions.
- Create projects and configure their devices in the CLI first. Slack project creation and hardware selection are not implemented.

No special template is required for ordinary questions or research directions. For example:

```text
지금까지 결과와 실패 원인을 정리하고, 다음에 검증할 비교 실험을 제안해줘.
```

Questions use the normal Codex reply worker and consume account allowance. Questions and summaries remain available after research time expires; they do not themselves renew research execution time.

## Commands

| Message | Action |
| --- | --- |
| `도움말` | Show the supported DM command guide. |
| `프로젝트 목록` | List projects and short IDs. |
| `프로젝트 선택 My research` | Select the project for new DM threads. |
| `상태` | Show the selected project's current state, remaining time and active experiments. |
| `사용량` | Show the account's reported remaining allowance. |
| `새 실험: Compare A with baseline B` | Save a small experiment request in this project. |
| `일시정지` | Pause scheduling new work; current work can finish. |
| `중지` | Request cancellation of the project's running and queued work. |
| `재개 1시간 사용량 10%p` | Continue the same session for a fresh hour with a 10-percentage-point allowance decrease. |
| `재개 1시간 보호 끄기` | Explicitly continue for one hour with the allowance guard disabled. |

Command parsing, status/control replies and experiment-request registration do not call an LLM. Designing, reviewing and running the requested study still uses the existing research pipeline and account allowance. See [adding a small experiment](experiment-requests.md).

The allowance decrease is measured in **percentage points**, not a proportion of the starting allowance: starting at 50% remaining with `10%p` stops at 40%. A continuation keeps the original project/session, workspaces, conversation, results and cumulative usage; it captures a fresh allowance baseline. A valid device configuration and fresh usage readings are still required when that guard is enabled.

## Inspect or disconnect

Run these in your terminal:

```sh
braindance slack status
braindance slack remote-status
braindance slack remote-off
braindance slack remote-forget
```

`remote-off` disables incoming commands and keeps the app token. `remote-forget` removes that token. Existing result notifications remain independent. `braindance slack disconnect` disconnects the bot and disables incoming commands too. Disconnecting does not cancel research work that was already accepted; use `중지` or the CLI's Stop action for that.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| “Sending messages to this app has been turned off.” | Enable Messages-tab input in **App Home**, then reopen the app DM or refresh Slack. |
| Reports arrive, but commands have no response. | Run `braindance slack remote-status`. Verify incoming commands are enabled, Socket Mode is connected, and `message.im` is saved under **Enable Events**. Check the message's thread for the reply. |
| A message sent before setup gets no reply. | Send a new `프로젝트 목록` after the connection and subscriptions are ready. Historical DM commands are not fetched and replayed automatically. |
| `im:history` is missing. | Add the bot scope, reinstall the app, and update `/slack` if its bot token changed. |
| Socket Mode keeps retrying. | Use an `xapp-` token with `connections:write` from the same app as the result bot, verify Socket Mode is enabled, and check network access. |
| A reply targets an earlier project. | Existing threads keep their project. Send `프로젝트 선택 …` in a new top-level DM. |
| Claude is logged in but usage is unavailable / HTTP 429. | Authentication, model responses and allowance retrieval are separate checks. Wait for the existing usage-query backoff. A guarded start needs fresh readings; disabling that guard requires an explicit choice. Do not infer a remaining percentage from successful login or one successful response. |

Incoming messages are checked against the owner, workspace, bot authorization and DM channel. Bot messages, edits and other-user events are ignored. Event IDs and outgoing replies are retained to suppress duplicates. An interrupted control whose outcome is uncertain is held for inspection rather than repeated automatically.

[Back to README](../README.md)
