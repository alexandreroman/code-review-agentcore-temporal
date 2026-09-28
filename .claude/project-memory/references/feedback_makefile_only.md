---
name: "Makefile as the single entry point"
description: "Every operational step is a make target; targets delegate to shell scripts in scripts/"
type: feedback
---

# Makefile as the single entry point

Every operational step (deploy, secrets, session kill, info panel, worktree
init) is a Makefile target. A target runs one command or delegates to a bash
script in `scripts/` (`set -euo pipefail`); logic never grows inside a recipe,
since macOS ships GNU Make 3.81, which has no `.ONESHELL`: each recipe line
runs in its own shell.
Python is used only where a script cannot reasonably do the job (for example
the GitHub App manifest flow, which serves a localhost page). `.casper.json`
scripts only call `make`.

**Why:** one self-documenting entry point for developers and demos, with the
deployment logic kept in plain, readable scripts.

**How to apply:** add a Makefile target; put anything beyond one command in a
`scripts/*.sh` file that the target calls.
