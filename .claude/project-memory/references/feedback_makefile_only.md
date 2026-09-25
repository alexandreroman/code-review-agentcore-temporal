---
name: "Makefile only"
description: "Operational automation goes through Makefile targets, never shell scripts"
type: feedback
---

# Makefile only

Every operational step (deploy, secrets, session kill, info panel, worktree
init) is a Makefile target. The repository contains no `.sh` scripts. A small
Python module run with `uv run` from a target is acceptable when a recipe
cannot reasonably do the job (for example the GitHub App manifest server).
`.casper.json` scripts only call `make`.

**Why:** a single, self-documenting entry point for developers and demos.

**How to apply:** add a Makefile target instead of a script.
