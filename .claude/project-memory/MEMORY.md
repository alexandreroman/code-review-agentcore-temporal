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

- [Project objective](references/project_objective.md) — 15-min live demo, four moments; reliability and lean artifacts first
- [Stack choices](references/project_stack.md) — mTLS, Claude via Bedrock and IAM, Python, make dev against Temporal Cloud
- [Demo app is Java / Spring Boot](references/project_demo_app_java.md) — reviewed repo is Java for enterprise audiences
- [Design docs location](references/reference_design_docs.md) — specs, plans, decisions, status and spike results in git-ignored docs/
- [Makefile as the single entry point](references/feedback_makefile_only.md) — make targets delegate to scripts/*.sh; logic never in recipes
- [Ask before implementing](references/feedback_ask_before_implementing.md) — present a plan and wait for approval before carrying it out
- [English only for generated text](references/feedback_english_only.md) — all generated text (code, docs, commits, memory) is in English
- [Project title and code name](references/project_naming.md) — title in docs, code name in code, short component prefix, app name
- [Amend unpushed commits instead of stacking fixes](references/feedback_amend_unpushed.md) — fold fixes into their unpushed commit
- [Public repository hygiene](references/feedback_public_repo_hygiene.md) — placeholders, generic docker, Casper confined
- [Tests cover business logic only](references/feedback_tests_business_only.md) — pure rule functions: review, routing, contract, GitHub errors
- [Observability choices](references/project_observability.md) — opt-in TRACING, OTel + SigV4 exporter, Transaction Search set by the owner
- [Docs focus on the AgentCore x Temporal integration](references/feedback_readme_focus.md) — deployable reference; no make dev in README
- [One make up deploys everything](references/project_single_make_up.md) — the only deploy command; step targets hidden
- [Teaser video](references/project_teaser_video.md) — Remotion source in git-ignored docs/video/; only the MP4 is committed
- [Timeout layering rule](references/project_timeout_layering.md) — inner layers give up first; every activity heartbeats (5 s / 10 s)
- [Web pages carry no decorative status indicators](references/feedback_ui_no_decorative_status.md) — no live badge or pulsing dot; state only on error
