# Project Memory

> When a new decision **contradicts** an existing
> memory note, do NOT silently override it.
> Instead: surface the conflict, quote the
> existing memory, explain how the new decision
> differs, and ask for explicit confirmation
> before updating. **Do NOT take any action** —
> no tool calls, no file writes — until confirmed.

> **Note wording** — state permanent facts in the
> present tense. A note read out of context must
> not reveal what it replaces or what just
> happened. Ban narration markers: "now", "no
> longer", "previously / used to", "reverses /
> replaces", "kept", "changed to", "reintroduce",
> "the user asked to". Phrase prohibitions
> positively ("the API is versioned under /v2"),
> not as the negation of a former state. Test:
> remove the note from its context — if a sentence
> only makes sense knowing the prior state,
> rewrite it.

- [Project objective](references/project_objective.md) — 15-min talk, two screens, four moments; stage reliability first
- [Stack choices](references/project_stack.md) — mTLS, Anthropic API (no Bedrock), Python, and why
- [Local dev uses Temporal Cloud](references/project_dev_on_temporal_cloud.md) — no local Temporal server; make dev targets Cloud
- [Design docs location](references/reference_design_docs.md) — spec, plans, decisions and spike results in git-ignored docs/
- [Makefile as the single entry point](references/feedback_makefile_only.md) — make targets delegate to scripts/*.sh; logic never in recipes
- [Ask before implementing](references/feedback_ask_before_implementing.md) — present a plan and wait for approval before carrying it out
- [English only for generated text](references/feedback_english_only.md) — all generated text (code, docs, commits, memory) is in English
- [Project title and code name](references/project_naming.md) — title in docs, code-review-agentcore-temporal in code, app name for GitHub
- [Amend unpushed commits instead of stacking fixes](references/feedback_amend_unpushed.md) — fold fixes into the unpushed commit they correct
- [Placeholders for account identifiers](references/feedback_no_real_identifiers.md) — real namespace/account/app IDs only in .env, never tracked
- [No maintainer specifics in public files](references/feedback_no_maintainer_specifics.md) — generic docker, no Casper in public files
- [Tests cover business logic only](references/feedback_tests_business_only.md) — pure review/routing logic only; no plumbing or constant tests
- [Lean, optimized artifacts](references/feedback_lean_artifacts.md) — small images/zips from the start, few moving parts
