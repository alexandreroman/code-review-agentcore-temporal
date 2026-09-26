---
name: "Design docs location"
description: "Where the approved spec, the plans and the spike results live"
type: reference
---

# Design docs location

The approved design spec, the implementation plans and the spike results live
under `docs/superpowers/` (`specs/`, `plans/`, `spike/RESULTS.md`). The whole
`docs/` directory is git-ignored on purpose: these documents are never
committed. Repository-facing docs (`README.md`, `SETUP.md`, `DEMO.md`) live at
the repository root.

**Why:** the spec is the binding authority for every implementation plan.

**How to access:** read
`docs/superpowers/specs/2026-09-25-temporal-agentcore-review-demo-design.md`
before implementation work; read `docs/superpowers/STATUS.md` for the
hand-off status between conversations; never `git add -f` anything under
`docs/`.
