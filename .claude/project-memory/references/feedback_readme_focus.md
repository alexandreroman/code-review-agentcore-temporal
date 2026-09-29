---
name: "Docs focus on the AgentCore x Temporal integration"
description: "README pitches a deployable reference for Serverless Workers on AgentCore; no docs mention a conference or a talk"
type: feedback
---

# Docs focus on the AgentCore x Temporal integration

`README.md` presents the repository as a complete, deployable reference for
running agents on Temporal Serverless Workers on Amazon Bedrock AgentCore
Runtime: why the integration matters, then how this project uses it.
Temporal Cloud starting the workers, so that nobody launches or hosts one,
is a key selling point. The README leaves out the local dev worker
(`make dev`, the `dev/` branch queue), which `SETUP.md` covers.

No documentation file (README, SETUP, DEMO, CLAUDE.md) mentions a
conference, a talk or a stage: `DEMO.md` is the timed run-through of a
live demo, and its vocabulary is "demo", "live", "key points".

**Why:** the talk format and the dev setup distract the reader from the
repository's role.

**How to apply:** when editing the docs, keep the README tied to the
integration and to what a reader deploys with `make up`; say "demo" or
"live demo" wherever an event would otherwise be named.
