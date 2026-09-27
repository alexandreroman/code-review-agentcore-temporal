---
name: "Tests cover business logic only"
description: "Unit tests target the pure review and routing logic; workflows, infra, tooling and plumbing have none"
type: feedback
---

# Tests cover business logic only

Unit tests cover the business logic: the shared contract, the webhook
routing and command rules, and the pure review modules the workflows call
(hunks, batching, navigation, lifecycle, publishing, prompts, limits).
Workflows, agents, infrastructure (OpenTofu), the Makefile, the deployment
tooling (`agentcore_review_tools`) and the runtime plumbing (entry points,
settings, drain, HTTP clients) have no unit tests; the e2e-validation skill
exercises them for real.

**Why:** the project is a teaching-oriented conference demo; tests of
infrastructure, tooling or library behaviour cost maintenance and teach
nothing.

**How to apply:** write tests only for code carrying business rules; never
test constants or pydantic behaviour; verify infrastructure and tooling
changes by running the targets (`make infra-check`, `make deploy`,
`make ping`) or the e2e-validation skill.
