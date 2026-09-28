---
name: "Tests cover business logic only"
description: "Unit tests target the pure review, routing and contract rules; workflows, infra, tooling and plumbing have none"
type: feedback
---

# Tests cover business logic only

Unit tests cover the business logic: the pure modules carrying review,
routing or contract rules. Workflows, agents, infrastructure (OpenTofu), the
Makefile, the deployment tooling (`agentcore_review_tools`) and the runtime
plumbing (entry points, settings, drain, HTTP clients) have no unit tests;
the e2e-validation skill exercises them for real.

**Why:** the project is a teaching-oriented conference demo; tests of
infrastructure, tooling or library behaviour cost maintenance and teach
nothing.

**How to apply:** write tests only for code carrying business rules; never
test constants or pydantic behaviour; verify infrastructure and tooling
changes by running the targets (`make infra-check`, `make deploy`,
`make ping`) or the e2e-validation skill.
