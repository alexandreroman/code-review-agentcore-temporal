---
name: "One make up deploys everything"
description: "make up does the whole first deployment, GitHub App and demo repository (from demo/) included; step targets hidden"
type: project
---

# One make up deploys everything

`make up` is the single deployment command, first run and code updates
alike. Its GitHub step (`scripts/github.sh`) registers the GitHub App when
none is stored (browser confirmation), opens the install page and waits
for the installation, applies the rulesets, and pushes the demo
application embedded in `demo/` (`baseline/` sources and
`customer-search.patch`, rebuilt into the `baseline` and
`scenario/customer-search` tags) while the demo repository
(`$GITHUB_OWNER/$DEMO_REPO`, `DEMO_REPO` defaulting to
`agentcore-review-demo-app`) has no branch. The "Reset demo" workflow runs
only right after that push, so a routine `make up` never resets the demo.
The demo application evolves in `demo/`, never in a separate upstream
repository, so no tracked file names a GitHub owner. The step targets
(`bootstrap`, `infra`, `secrets`, `deploy`, `github-app`, `github`,
`infra-init`, `router-build`) stay callable but are left out of
`make help` and of the docs, which name `make up` only.

**Why:** a reader deploys the whole demo with one command; the two
browser clicks GitHub imposes (create and install the app) happen inside
that run.

**How to apply:** new deployment steps join the `make up` chain and stay
idempotent; docs point to `make up`, never to a step target, except for
troubleshooting (`make github-app FORCE=1`, `make infra-init`).
