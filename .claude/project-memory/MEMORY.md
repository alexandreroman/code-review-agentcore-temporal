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

- [Project objective](references/project_objective.md) — 15-min talk, four moments; stage reliability and lean artifacts first
- [Stack choices](references/project_stack.md) — mTLS for Temporal, Claude via Bedrock and IAM only, Python, and why
- [Demo app is Java / Spring Boot](references/project_demo_app_java.md) — reviewed repo is Java for enterprise audiences
- [Local dev uses Temporal Cloud](references/project_dev_on_temporal_cloud.md) — no local Temporal server; make dev targets Cloud
- [Design docs location](references/reference_design_docs.md) — specs, plans, decisions, status and spike results in git-ignored docs/
- [Makefile as the single entry point](references/feedback_makefile_only.md) — make targets delegate to scripts/*.sh; logic never in recipes
- [Ask before implementing](references/feedback_ask_before_implementing.md) — present a plan and wait for approval before carrying it out
- [English only for generated text](references/feedback_english_only.md) — all generated text (code, docs, commits, memory) is in English
- [Project title and code name](references/project_naming.md) — title in docs, code-review-agentcore-temporal in code, app name for GitHub
- [Amend unpushed commits instead of stacking fixes](references/feedback_amend_unpushed.md) — fold fixes into the unpushed commit they correct
- [Placeholders for account identifiers](references/feedback_no_real_identifiers.md) — real namespace/account/app IDs only in .env, never tracked
- [No maintainer specifics in public files](references/feedback_no_maintainer_specifics.md) — generic docker, no Casper in public files
- [Tests cover business logic only](references/feedback_tests_business_only.md) — pure rule functions: review, routing, contract, GitHub errors
- [Temporal UI labels and details](references/project_temporal_ui_labels.md) — short activity type names, summaries hold the detail only
- [Observability choices](references/project_observability.md) — opt-in TRACING, OTel + SigV4 exporter, Transaction Search set by the owner
- [Docs focus on the integration](references/feedback_readme_focus.md) — deployable AgentCore x Temporal reference; no talk, no conference, no make dev in README
- [One make up deploys everything](references/project_single_make_up.md) — GitHub App, install wait, demo repo pushed from demo/ inside make up; step targets hidden
