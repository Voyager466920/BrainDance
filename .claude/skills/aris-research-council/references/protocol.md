# Protocol and run contract

## Participants and isolation

The user-selected four members replace the upstream council's five generic advisors:

- **Claude Novelty:** distinguish the proposal from the supplied literature; identify closest prior work and evidence gaps.
- **Claude Method:** specify a falsifiable hypothesis, baselines, controls, metrics, and the smallest useful experiment.
- **Claude Skeptic:** identify leakage, confounding, missing counterevidence, failure criteria, and cheap disconfirmation.
- **Codex:** independently propose a hypothesis from the same literature, then separately validate the anonymous proposals. Use official ARIS `mcp-servers/codex-exec/server.py`, not a replacement reviewer server.

Claude specialists are native `Agent` subagents described in project `.claude/agents/council-{novelty,method,skeptic}.md`. The runner supplies model overrides and bounded prompts; the definitions' Sonnet model is the interactive fallback. Generation and review use fresh contexts. Reviewers receive the common question, evidence digest, and anonymous proposals, not earlier reviewer deliberations or the author map. The Claude Chairman synthesizes in a separate fresh session after all reviews exist. These are role-diverse Claude perspectives plus one independently executed Codex perspective, not four independent model families.

## Rounds

1. Freeze a neutral question, constraints, literature digest, and evidence identifiers shared by all four generators. Do not include another member's proposal. Each returns evidence-linked hypotheses and uncertainty; never infer novelty from absence in a small search alone.
2. Preserve original outputs. Apply the upstream factorial/Lehmer shuffle generalized to four participants (`timestamp mod 4!`), remove explicit role/model identity, and label **Response A–D**. Persist the map for audit, but keep it out of every review prompt. Anonymity is best effort: content can still reveal a specialist's reasoning style.
3. Three fresh Claude subagents and a fresh Codex call each review the same four anonymous responses. Answer: **Which response is strongest and why? Which has the biggest blind spot? What did all four miss?** Require evidence IDs, falsification conditions, and explicit unsupported claims. Review must not become a second literature search or an unbounded tool loop.
4. Claude Chairman receives the responses, all reviews, and evidence. Use the upstream five-part synthesis: **Where the Council Agrees; Where the Council Clashes; Blind Spots the Council Caught; The Recommendation; The One Thing to Do First.** Prefer stronger evidence over majority votes, preserve real disagreements, and explain any minority override. Record structured hypothesis assessments separately for the tree.
5. Persist inputs, raw outputs, stderr, anonymous prompts, audit map, usage receipts, decisions, and tree records even when a round fails. Missing members or invalid outputs make the run incomplete; do not label it a completed council. Fix a concrete configuration error before retrying and charge retries against limits.

## Invocation

From the project root, provide your own ARIS literature review and evidence records. Research inputs and results are private runtime data and are not distributed with this repository:

```sh
python3 .claude/skills/aris-research-council/scripts/council.py run \
  --topic "Can VLA camera-shift adaptation be tested with minimal computation? Plan only; no GPU execution." \
  --literature inputs/LITERATURE.md \
  --evidence inputs/evidence.json \
  --mode balanced
```

`--config FILE` overlays the selected mode. `--aris-repo` defaults to `~/aris_repo`. Optional `--node-id` selects an existing active/expanded branch; without it a new topic starts a problem node. `--db` defaults to `.aris/council/tree.sqlite3`; `--output` defaults to a unique run folder under `council/`. The run saves resolved `config.json`, `status.json`, `usage.json`, evidence snapshots, per-stage raw logs, and `round-1/COUNCIL_REPORT.md`.

For an interrupted run, repeat its original arguments with the **same `--output` plus `--resume`**. Resume requires identical configuration, topic, database, requested parent node, and literature/evidence contents. Frozen original evidence is never overwritten by changed input. Completed stages reuse their actual parsed output receipts without model redispatch. Dispatched failed or ambiguous call logs stop continuation rather than trigger an automatic retry. A run whose tree commit has started/completed also stops so the operator can inspect persisted nodes before taking further action. Resume is recovery of a partially completed run, not another evaluation of an already committed council.

If correcting a diagnosed failure manually, preserve the original raw logs and account for any dispatched usage before continuing. A known coordinator output-cap failure before child dispatch can be corrected without rerunning completed generation, but this must not become a generic rule to delete ambiguous failures or reset budgets.

Open the tree and mutate status or priority in the Viewer. Its **Branch** action adds a child without calling a model. To evaluate that branch, copy its ID and start `run --node-id ID --db SAME_DB` with the saved literature/evidence arguments. Held or discarded nodes must be reactivated before expansion. Depth limits apply to stored nodes, not just the number of council rounds.

```sh
python3 .claude/skills/aris-research-council/scripts/viewer.py \
  --db .aris/council/tree.sqlite3 --port 8766 --max-depth 3

python3 .claude/skills/aris-research-council/scripts/tree_store.py \
  --db .aris/council/tree.sqlite3 --out .aris/council/tree-export.json
```

The Viewer serves `http://127.0.0.1:8766` for local inspection. Do not expose it on the public network. JSON export is a portable snapshot; SQLite is the transaction-backed working store. Export includes paper references, source evidence, evaluations, expected experiments, parent/child relationships, state, priority, and audit events. Viewing, branching in the Viewer, or reprioritizing does not call models.

## Limits and modes

Lite, Balanced, and Deep retain all four participants and both independent generation and blind review; none silently omits Codex or peer review. Models are requested aliases; execution receipts establish actual resolved models.

| Setting | Lite | Balanced (default) | Deep |
| --- | --- | --- | --- |
| Generation / peer / Chairman | Haiku / Haiku / Sonnet | Sonnet / Haiku / Sonnet | Sonnet / Sonnet / Opus |
| Codex model | `gpt-6-luna` | `gpt-6-luna` | `gpt-6.1-sol` |
| Participant concurrency | 2 | 3 | 4 |
| Maximum tree depth | 2 | 3 | 4 |
| Maximum councils | 1 | 2 | 3 |
| Model-invocation limit | 13 | 22 | 33 |
| Token admission/stop budget | 250,000 | 500,000 | 1,000,000 |
| Context character limit | 7,000 | 14,000 | 24,000 |
| Requested output-token cap | 1,800 | 2,600 | 4,000 |

All modes default to `rounds: 1`, `optimized: true`, `max_papers: 8`, `timeout_seconds: 900`, `codex_effort: "xhigh"`, and `coordinator_model: "haiku"`. `claude_budget_usd: 8.0` is passed to **each Claude session**, not an aggregate council dollar ceiling. Codex has no equivalent aggregate monetary cap here. `codex_disabled_mcps` defaults to `["node_repl", "computer-use"]`; global registrations stay unchanged. Print the authoritative resolved presets with `python3 .claude/skills/aris-research-council/scripts/council.py modes`.

A small override file can contain only the fields to change:

```json
{
  "rounds": 1,
  "max_councils": 1,
  "max_model_calls": 11,
  "max_parallel": 3,
  "max_depth": 3,
  "token_budget": 500000,
  "timeout_seconds": 900
}
```

Other supported overrides are the model keys `generation_model`, `peer_model`, `chairman_model`, `coordinator_model`, `codex_model`, and `codex_effort`; context keys `optimized`, `context_chars`, `output_tokens`, and `max_papers`; and `claude_budget_usd`/`codex_disabled_mcps`. Unknown keys fail before dispatch. `max_parallel` must be 1–4, and `rounds` cannot exceed `max_councils`. Increasing `max_councils` alone does not launch extra rounds. Tree depth/status and budgets can stop a requested later round while retaining earlier work.

Balanced and Deep dispatch 11 logical model invocations per complete council: two Claude coordinator sessions, six Claude subagents, two Codex stages, and one Chairman. Lite's two-agent concurrency requires four coordinator sessions and 13 invocations; concurrency one requires 15. These count model sessions/agents, not internal provider inference turns. A lower call budget cannot complete that protocol. Calls already in flight can cross an observed token threshold; the CLIs do not provide an aggregate provider-enforced hard token ceiling. Log estimates, actual usage, cached usage, and unavailable fields distinctly. Do not auto-increase an exhausted limit or retry an indefinitely failing member.
