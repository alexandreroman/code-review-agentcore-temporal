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

- [Project objective](references/project_objective.md) — 15-min conference demo of Temporal + AgentCore PR reviews
- [Stack choices](references/project_stack.md) — Temporal Cloud mTLS, Anthropic API, Python, OpenTofu, and why
- [Local dev uses Temporal Cloud](references/project_dev_on_temporal_cloud.md) — no local Temporal server; dev queue review-dev
- [Design docs location](references/reference_design_docs.md) — spec, plans and spike results live in git-ignored docs/
- [Makefile only](references/feedback_makefile_only.md) — automation goes through Makefile targets, never .sh scripts
- [Ask before implementing](references/feedback_ask_before_implementing.md) — confirm with the user before starting a plan or app code
