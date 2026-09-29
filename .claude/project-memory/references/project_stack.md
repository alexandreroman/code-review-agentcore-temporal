---
name: "Stack choices"
description: "mTLS for Temporal, Claude via Bedrock and IAM, Python, make dev against Temporal Cloud, and why"
type: project
---

# Stack choices

- Temporal Cloud authenticates every client with mTLS certificates only.
- Claude is reached only through Amazon Bedrock, authorized by the
  caller's IAM identity (the runtime role on AgentCore, the developer's
  credentials in the dev worker).
- The orchestrator is in Python: the Temporal Python SDK is the only one
  with an official AgentCore sample and the Strands Agents plugin.
- `make dev` runs the local worker against the Temporal Cloud namespace,
  on the dev task queue; the project has no local Temporal server and no
  Compose file.

**Why:** Bedrock and mTLS keep every credential inside AWS IAM and the
certificate pair; Python gives the demo its AgentCore sample and agent
plugin; real GitHub events and the real Lambda router are part of the dev
loop, so only the task queue differs between development and production.

**How to apply:** model access through Bedrock and IAM only, Temporal
access through mTLS only, orchestrator in Python; never add a
`temporal server start-dev` service, even where skillbox conventions
suggest one.
