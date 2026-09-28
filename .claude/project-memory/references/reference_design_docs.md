---
name: "Design docs location"
description: "Where the design specs, plans, decisions, status and spike results live"
type: reference
---

# Design docs location

The design documents live in `docs/superpowers/`, on the maintainer's
machine only: the design specs in `specs/`, the implementation plans in
`plans/`, the spike results in `spike/`, plus `DECISIONS.md` (answers to
the plans' open questions) and `STATUS.md` (implementation status, the
entry point for a new session). The whole `docs/` directory is git-ignored:
these documents are never committed. The public reference is `README.md`,
`SETUP.md` and `DEMO.md` at the repository root.

**Why:** background for design questions, kept out of the public
repository.

**How to access:** start from `STATUS.md`; read the specs for the intent
behind a design choice; never `git add -f` anything under `docs/`; never
point public files or code comments at `docs/`.
