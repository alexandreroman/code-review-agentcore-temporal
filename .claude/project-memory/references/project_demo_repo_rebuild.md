---
name: "Demo repository rebuild"
description: "make demo-reset rebuilds the demo repository's history from demo/: ships a scenario change, PRs start clean"
type: project
---

# Demo repository rebuild

`make demo-reset` rebuilds the demo repository's history from `demo/` with
new commits, force-pushes `main` (at `baseline`) and the `baseline` and
`scenario/customer-search` tags, then runs the **Reset demo** workflow,
which closes open PRs and recreates the scenario branches. The pull
requests then start from a clean slate: earlier PRs still exist in the
repository, but GitHub does not present them when a new PR is opened. The
Reset demo workflow alone reuses the same commits, so GitHub keeps
presenting earlier PRs.

**Why:** `make up` pushes the demo only into an empty repository, and a demo
whose PR page lists earlier runs distracts the audience.

**How to apply:** run `make demo-reset` (or `/demo-reset`) after a change to
`demo/`, or to clear earlier PRs before a live demo. The owner runs it
(`! YES=1 make demo-reset`): the force-push bypasses the `main` and `tags`
rulesets as an admin, and auto mode refuses it. The commits get new SHAs on
every run, even when `demo/` is unchanged.
