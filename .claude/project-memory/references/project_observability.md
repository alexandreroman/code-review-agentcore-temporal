---
name: "Observability choices"
description: "Opt-in tracing with plain OpenTelemetry and a SigV4 exporter; heartbeats as the only worker metrics"
type: project
---

# Observability choices

- Tracing is opt-in behind `TRACING` (Makefile variable, `off` by
  default). It uses temporalio's `OpenTelemetryPlugin` and replay-safe
  tracer provider with a small SigV4-signed OTLP/HTTP exporter to the
  X-Ray OTLP endpoint; the project does not use `aws-opentelemetry-distro`
  or `opentelemetry-instrument`. With tracing off, neither the plugin nor
  the exporter exists.
- CloudWatch Transaction Search is enabled by the account owner, outside
  OpenTofu: the stacks create no Transaction Search, X-Ray destination or
  indexing resource.
- Each pull request action (round, fix, reply, idle step, close) is a
  root span linked to the signals that queued it, so a long-lived
  `PullRequestWorkflow` never becomes one multi-day trace.
- Worker metrics are Temporal worker heartbeats only (every 10 s, shown
  on Temporal UI's Workers page); no metrics are exported.

**Why:** few moving parts and a lean image for the demo; the account-wide
Transaction Search setting (and its billing) stays the owner's decision.

**How to apply:** keep tracing changes inside this design; never add a
Transaction Search resource to `infra/`, and keep the off mode free of
any OpenTelemetry side effect.
