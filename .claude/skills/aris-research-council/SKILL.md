---
name: aris-research-council
description: Add three Claude specialists, an independent Codex participant, and a Claude Chairman as an advisory Council to the installed ARIS autonomous research pipeline. Use for evidence-linked idea or result review, persistent research trees, and shared-project research in BrainDance.
---

# ARIS Research Council

Keep the official ARIS `research-pipeline` as the main autonomous executor. Its `idea-discovery`, `experiment-bridge`, `auto-review-loop`, and original independent Reviewer remain in charge of implementation, debugging, experiments, quality gates, and termination. Council supplements that workflow; it does not replace the Reviewer or own a separate experiment-planning loop. Never alter upstream Skills.

Read [native-pipeline.md](references/native-pipeline.md) for the managed execution adapter, pause/resume, receipts, and legacy-session compatibility. The native worker loads the installed official Skills as a private plugin, invokes the actual pipeline and nested Skills, and retains one Claude session/workspace per project. The app and CLI share the same project conversation, user directions, immutable run receipts and token ledger.

For focused research, convene an **ideas Council** after literature/idea discovery, before experiments; convene a **results Council** after actual results, before the next comparison and final report. Council remains advisory. The original ARIS Reviewer independently reviews novelty, code and results according to the official workflow. Preserve disagreements and explain the chosen next action using evidence. Avoid asking either reviewer the identical question twice without new evidence; do not suppress ARIS's normal review loop.

For project paper scouting, read [scouting.md](references/scouting.md). Interests and bridge fields are project-scoped; the main executor cheaply screens retrieved papers and implements bounded pilots. Keep the original Reviewer; full ideas Council is skipped and measured promising results need results Council before reporting in the same conversation.

Use Balanced unless the human selects Lite or Deep. The existing `scripts/council.py run` executes actual Claude Novelty/Method/Skeptic subagents and independent Codex generation/review, anonymizes proposals, and obtains Claude Chairman synthesis. Read [protocol.md](references/protocol.md) for that protocol and its mode limits. Do not substitute role-played answers or invoke the complete upstream llm-council workflow on top of the same round.

Keep retrieved paper identifiers, URLs, original excerpts and abstracts, verification receipts, proposed experiments, assessments, actual results and errors attached to the research tree. Human-readable titles and reports are Korean; preserve original quotations and identifiers. Proposals are not measured results. Existing `council.py` CLI runs can still evaluate a selected branch without running experiments.

BrainDance's host supplies the selected local/SSH resources, read-only target exploration, reviewed immutable experiment execution and cumulative runtime/model budgets. The native executor writes and revises actual experiment source; all pilots, sanity checks, retries and ablations go through the same host broker. An enabled project automatic session is the execution authority; never raise its limits, change GPUs or invent an approval from model output. Manual plans retain code-specific approval. See [experiments.md](references/experiments.md) for the execution contract.

Preserve prior projects, sessions, evidence and ledgers. Running older sessions keep their execution method. An explicit resume of an inactive older session migrates to the native pipeline while retaining prior method/progress and all budgets/results as history. Show actual execution phases, model usage and missing prerequisites; do not claim completion from a banner, a proposed plan, a mocked test, or an absent receipt. Council conversations contain requests/responses and tool receipts, not hidden model reasoning.

Read [optimization.md](references/optimization.md) for context caching and model selection, and [provenance.md](references/provenance.md) for reused code. Keep global Claude/Codex configuration intact. Use BrainDance branding in the product interface.
