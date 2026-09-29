---
name: "One make up deploys everything"
description: "make up is the only deploy command, demo repository from demo/ included; step targets stay out of help and docs"
type: project
---

# One make up deploys everything

`make up` is the only deployment command, first run and code updates
alike, GitHub App registration and installation included. The "Reset
demo" workflow runs only right after the first push of the demo
application to an empty demo repository, so a routine `make up` never
resets the demo. The demo application evolves in `demo/`, so no tracked
file names the demo repository's owner. The step targets (`bootstrap`,
`infra`, `secrets`, `deploy`, `github`, `infra-init`, `router-build`)
stay callable but out of `make help` and of the docs, except
`make github FORCE=1` and `make infra-init` for troubleshooting.

**Why:** a reader deploys the whole demo with one command; the two
browser clicks GitHub imposes (create and install the app) happen inside
that run.

**How to apply:** new deployment steps join the `make up` chain and stay
idempotent; docs point to `make up`, never to a step target, except for
the two troubleshooting commands above.
