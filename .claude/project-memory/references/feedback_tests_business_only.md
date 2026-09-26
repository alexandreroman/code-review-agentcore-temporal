---
name: "Tests cover business logic only"
description: "Unit tests target the core review logic; infrastructure, tooling and plumbing have none"
type: feedback
---

# Tests cover business logic only

Unit tests cover the core business logic of the app: the shared contract,
the review logic (hunks, findings, batching, navigation tools), the webhook
routing, and later the workflows and agents. Infrastructure (OpenTofu), the
Makefile, the deployment tooling (`agentic_review_tools`) and the runtime
plumbing (entry points, settings, drain) have no unit tests; they are checked
by running them for real.

**Why:** the project is a demonstrative, teaching-oriented conference demo;
tests of infrastructure and tooling cost maintenance and teach nothing.

**How to apply:** write tests only for code carrying business rules; verify
infrastructure and tooling changes by running the targets (`make infra`,
`make deploy`, `make ping`, live checks).
