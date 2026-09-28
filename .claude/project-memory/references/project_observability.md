---
name: "Observability choices"
description: "Opt-in tracing with plain OpenTelemetry and a SigV4 exporter; heartbeats as the only worker metrics"
type: project
---

# Observability choices

- Tracing is opt-in (`TRACING`, off by default). Its only OpenTelemetry
  pieces are temporalio's `OpenTelemetryPlugin` with its replay-safe
  provider, the Strands spans, and a small SigV4-signed OTLP/HTTP exporter
  to the X-Ray endpoint; with tracing off, neither plugin nor exporter
  exists.
- CloudWatch Transaction Search is enabled by the account owner, outside
  OpenTofu: the stacks create no Transaction Search, X-Ray destination or
  indexing resource.
- No metrics are exported beyond Temporal worker heartbeats.

**Why:** few moving parts and a lean image for the demo; the account-wide
Transaction Search setting (and its billing) stays the owner's decision.

**How to apply:** keep tracing changes inside this design; never add a
Transaction Search resource to `infra/`, and keep the off mode free of
any OpenTelemetry side effect.
