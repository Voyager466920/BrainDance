# Add a small experiment

Send `새 실험: <what to verify>` in a project's Slack conversation or the CLI composer in **대화 / auto** mode. `실험 추가:` and `new experiment:` are aliases. No code or JSON is required from you.

In Slack, select a project first or reply in a project/result thread. See [project selection](slack.md#choose-a-project-and-talk).

## A minimal request

```text
새 실험: 기존 모델의 KV 캐시를 절반으로 줄이고, 같은 평가 데이터에서 기준선 대비 정확도·추론 지연·최대 메모리를 비교해줘.
```

A useful request names the hypothesis, baseline, changing condition and metrics. You can ask the research executor to inspect the existing project code when you do not know its entry point:

```text
새 실험: 기존 프로젝트 코드를 먼저 확인해줘. 비동기 추론에서 관측 신선도가 성공률에 미치는 영향을 검증하고 싶어. 기존 체크포인트와 평가 환경을 재사용해서 지연 조건만 바꾼 최소 비교 실험을 설계하고 검증해줘.
```

The request is initially **unverified**. It is not a novelty claim, a measured result or an immediately executable plan. The original study pipeline checks prior art, refines the hypothesis, designs the comparison, authors and reviews code, then executes and analyzes it when permitted by the project state and limits. Evidence-based rejection can produce a report without a GPU run.

## What happens after sending

BrainDance immediately acknowledges the request with a short task ID and records a hypothesis, the full request and a durable independent task. Registration itself makes no LLM call.

| Project state | Behavior |
| --- | --- |
| Running with valid resources and remaining allowance/time | The request joins the study queue. Current work is preserved; existing selected-device concurrency controls scheduling. |
| Paused, stopped, blocked or expired | The request is saved. It does not resume work, renew time or change the allowance guard. |
| No research session yet | The request is saved for the project's first authorized session. Configure hardware and start research in the CLI. |
| Request hypothesis is held or discarded before dispatch | The queued request is retained and is not launched while inactive. |

Each task has its own workspace, code, logs and execution receipts while sharing the project conversation. It uses the existing selected server/GPU, deadline and allowance policy. Adding a request does not allocate a new GPU, expand limits or stop current work. Distinct authorized GPU slots can support concurrent studies; one selected GPU stays exclusive.

Repeated delivery of the same Slack event/request ID cannot create a second task. A deliberately sent new message has a new request ID and creates another request, even if its wording is identical.

## Continue a stopped project

After registering a request, send a separate explicit continuation in Slack:

```text
재개 1시간 사용량 10%p
```

This renews the same session for one hour and sets a stop line ten percentage points below its fresh starting account allowance. To choose time-only execution explicitly:

```text
재개 1시간 보호 끄기
```

Existing results, conversation, unfinished task workspaces and cumulative usage remain. These commands can fail if old work is still stopping, resources changed, authentication is unavailable or the guarded allowance snapshot cannot be read. A request acknowledgement is not proof that an experiment has started.

## CLI equivalents

Enter the same prefix directly in the shared composer, or use a one-shot command:

```sh
braindance chat "새 실험: Compare a smaller KV cache with the retained baseline for accuracy, latency and peak memory." --project "My research" --mode auto
braindance tasks --project "My research"
braindance history --project "My research" --full
```

For a scripted submission with a known idempotency key:

```sh
braindance chat "새 실험: Compare A with the existing baseline B." --project "My research" --mode auto --no-wait --request-id pilot-request-00000001
```

Reuse the same request ID and exact message/mode to check an uncertain submission. The same ID cannot be used to replace the request with different content. **Question-only / `--mode ask` does not register experiments**; it uses the ordinary reply worker.

To renew a stopped session from the terminal:

```sh
braindance auto resume --project "My research" --hours 1 --quota-drop-percent 10
```

## Follow up

Use the same Slack thread or CLI project conversation for questions and directions:

```text
현재 어떤 비교 실험을 준비하고 있어? 기준선과 평가 지표를 정리해줘.
```

```text
새 작업에서는 데이터셋과 체크포인트를 유지하고, 지연 조건만 바꿔줘.
```

A next-step direction keeps currently running code intact. Use `중지` to stop the project. The CLI's `/tasks` view and `braindance task stop TASK_ID --project "My research"` can stop one task. Task-level resume queues its saved workspace and does not itself resume the whole project.

Read execution state and retained measurements in **Progress**, **Experiments** and **Results**. Completed-study summaries appear in the same project conversation and follow the existing Slack/Notion reporting settings. Failures and missing measurements stay explicit; a completed process is not automatically a scientific success.

[Back to README](../README.md)
