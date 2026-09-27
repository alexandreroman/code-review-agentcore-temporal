---
name: "Design docs location"
description: "Where the design spec, plans, decisions and spike results live"
type: reference
---

# Design docs location

The design spec (`specs/2026-09-25-code-review-agentcore-temporal-design.md`),
the implementation plans, `DECISIONS.md` and the spike results live in
`docs/superpowers/`, on the maintainer's machine only. The whole `docs/`
directory is git-ignored: these documents are never committed. The public
reference is `README.md`, `SETUP.md` and `DEMO.md` at the repository root.

**Why:** background for design questions, kept out of the public
repository.

**How to access:** read the spec for the intent behind a design choice;
never `git add -f` anything under `docs/`; never point public files or code
comments at `docs/`.
