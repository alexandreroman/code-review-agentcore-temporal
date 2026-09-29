---
name: "Tests cover business logic only"
description: "Unit tests target pure functions carrying rules (review, routing, contract, GitHub error classification)"
type: feedback
---

# Tests cover business logic only

Unit tests cover pure functions carrying rules: review, routing, contract
and GitHub error classification. Workflows, agents, infrastructure
(OpenTofu), the Makefile, the deployment tooling (`agentcore_review_tools`)
and the runtime wiring (entry points, settings, drain, tracing) have none;
the e2e-validation skill exercises them for real.

**Why:** the project is a teaching-oriented live demo; tests of
infrastructure, tooling or library behaviour cost maintenance and teach
nothing.

**How to apply:** write tests only for code carrying business rules; never
test constants or pydantic behaviour; verify infrastructure and tooling
changes by running the targets (`make infra-check`, `make deploy`,
`make ping`) or the e2e-validation skill.
