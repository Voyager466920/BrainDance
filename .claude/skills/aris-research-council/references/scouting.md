# Paper scouting

The same official main pipeline uses research-lit and its normal nested Skills. Project settings hold interests, bridge fields, recency and per-query paper limits, pilot count/time, gain and seeds. The model cannot change project limits or devices.

Time defaults to automatic allocation from the remaining project budget and experiment slots. context.execution_budget is authoritative; pilot_seconds is only a hint under auto policy. The host allocates before code review, binds the exact code/arguments/runtime/directions/resources to its review receipt, and enforces the grant on the target. Code can read BRAINDANCE_TIMEOUT_SECONDS and BRAINDANCE_DEADLINE_UNIX; an absent or different internal timing guard alone is not a review blocker. Fixed runtime_policy is an advanced explicit per-pilot cap. Never raise total project time, experiment count, devices or model budgets.

paper_search runs the unmodified upstream arXiv/OpenAlex tools, retains raw stdout/stderr and dates, and caches canonical papers/queries per project. Register actual retrieved IDs with scout_candidates, including exact project interest, transferable mechanism, falsifiable hypothesis and experiment. Completed successful connections cannot be silently re-tested.

Skip full ideas Council for cheap scouting. The native executor writes pilots, gets the normal exact-code review, and uses the existing local/SSH broker. scout_triage reads actual measured receipts; require configured gain, distinct seeds, consistency and aggregate/seed agreement. Missing data and zero baselines remain inconclusive. A passing pilot needs results Council and the original Reviewer before detailed publication to the same project conversation. Negative pilots retain journal records and a concise status; they do not need heavy Council calls.

Use /interests and /scout in the TUI or interests/scout subcommands; the app/browser shares these settings. One start is a bounded batch, not an automatic recurring schedule. Original source evidence and errors remain intact while model excerpts are bounded.

Council paper citations resolve only explicit, unambiguous aliases from retained source metadata. Actual run UUIDs are independently allowlisted from host receipts, validated for reviews/assessments and stored in result_evidence_ids rather than masquerading as paper citations. Unknown IDs remain errors.
