# Token and context controls

## Applied controls

- **Progressive disclosure:** the short skill entrypoint routes here only for configuration or measurement. Agent prompts receive their role and a bounded evidence digest, not all skills or upstream manuals.
- **Fresh contexts:** separate generation, blind review, and Chairman contexts prevent accumulated transcripts from being replayed. Review needs the anonymous proposals, not the entire generation transcript. Shared frozen evidence is preloaded in native agent definitions, while coordinator `Agent` arguments stay short; it is not repeatedly copied through coordinator-generated tool arguments.
- **Model selection:** mode configuration controls models per phase. Balanced uses Sonnet for generation/Chairman and Haiku for peer review; Codex is independently configured. Report resolved model receipts, not just requested aliases. A failed/unavailable model must be reported or retried with a recorded compatible selection, never silently credited as participation.
- **Minimal MCP/tool surface:** generation and review need only their assigned evidence and output contract; Claude coordinator dispatches native agents, and Codex uses the official ARIS bridge. Do not enable all global MCP servers or attach a literature-search server to every member.
- **Cache and deduplicate:** cache extractive literature digests by content fingerprint and reuse exact inputs. Deduplicate paper identifiers/URLs before aggregation and consult stored ARIS literature/Research Wiki before another search. Cache hits save preprocessing/context repetition; a digest cache does not mean provider-side prompt-cache savings.
- **RTK:** use installed RTK for human-facing terminal inspection where useful. Preserve raw source material, model streams, stderr, and provider receipts before displaying a condensed version. RTK's command-output reduction does not by itself establish lower provider token usage.

`/compact` is an interactive Claude phase-boundary option after evidence, decisions, and pending tasks are persisted. Do not send it through a model prompt and claim compaction occurred. The automated runner's actual optimization is fresh bounded contexts. Compaction never replaces raw provenance.

## Measuring savings honestly

Report per-model/provider actual input, output, and cached-token fields when the CLI exposes them. Keep unknown fields unknown and distinguish requested model from a resolved model receipt. For the installed Claude CLI, result `usage` covers the main thread; sum per-model `modelUsage` to include native subagent leaves. Do not add result `usage` again or separately sum child events already represented in that aggregate. Preserve both raw receipts and the aggregation rule; if `modelUsage` is unavailable, label a main-thread-only fallback rather than claiming complete leaf totals.

Compare optimized and unoptimized input packages with the same task/evidence. An offline byte/character or approximate-token comparison measures **context size**, not billable provider savings. Label tokenization estimates and their method. A measured model-token comparison requires two actual executions with recorded matching scope, models, and complete receipts; it also incurs extra calls. A paired small-task benchmark measures that task's savings only; do not present it as a whole-council A/B experiment. Do not fabricate the baseline from a claimed compression percentage, and do not spend another full council merely to make a decorative comparison.

The token budget uses preflight/admission estimates and observed-usage stop checks. Parallel requests can finish after a limit is reached; hard monetary ceilings must be enforced by the provider/account controls when available. Never promise a strict aggregate bill ceiling from local token estimates.

## Optional measured small-task benchmark

After a council run has saved both full and compact contexts, use:

```sh
python3 .claude/skills/aris-research-council/scripts/benchmark.py \
  --run EXISTING_RUN_DIRECTORY --output NEW_EMPTY_BENCHMARK_DIRECTORY
```

This performs **four additional actual model invocations**: before/after primary-paper-ID extraction with the same Sonnet model, and before/after with the same Codex model. It sets Claude’s per-response output cap to 1,024 tokens and uses a separate 250,000-token admission/stop budget. The official Codex bridge has no output-cap argument: Codex receives a short JSON response contract, not an enforced 1,024-token provider cap. Claude CLI continuation/retry can also make a session’s cumulative output exceed its per-response cap. It preserves prompts, raw responses, usage, answers, and `comparison.json`. The before and after tasks check the same paper-ID set and an abstract-evidence caveat. Report output correctness along with usage differences; a smaller wrong answer is not an optimization success.

There is one observation per provider/variant (`n=1`). Full context runs first, so caching/order effects and output/reasoning variation remain confounders. This is measured token usage on a small extraction task, **not** an end-to-end council A/B or evidence that hypothesis/review quality is equivalent. The two provider pairs use fixed models within each pair; they are not direct model-quality comparisons.

## Why claude-mem is not installed

ARIS Research Wiki already maintains durable paper and idea context. This extension adds explicit evidence snapshots, a digest cache, and an auditable hypothesis/evaluation tree. Automatically injecting another memory system would duplicate stored research and expand hidden context. Add claude-mem only after a concrete retrieval gap is demonstrated and its installation is explicitly in scope; this implementation does not require or install it.

## Official references checked

- Claude [Skills](https://code.claude.com/docs/en/skills): progressive disclosure and skill discovery.
- Claude [Subagents](https://code.claude.com/docs/en/sub-agents): isolated context, tool restrictions, and agent model selection.
- Claude [Costs](https://code.claude.com/docs/en/costs): context management, compaction, and usage considerations.
- RTK [features](https://github.com/rtk-ai/rtk/blob/develop/docs/usage/FEATURES.md): command output filtering.
- OpenAI [Codex iterative repair loops](https://developers.openai.com/cookbook/examples/codex/build_iterative_repair_loops_with_codex): auditable bounded tool execution.

Provider capabilities can change; inspect current CLI help and official documentation before relying on a new flag or billing field.
