---
name: "Stack choices"
description: "Why the project uses Temporal Cloud mTLS, the Anthropic API, Python and OpenTofu"
type: project
---

# Stack choices

- Existing Temporal Cloud namespace in AWS `ca-central-1`, authenticated
  with mTLS client certificates; Serverless Workers on AgentCore is a
  prerelease feature enabled on this namespace.
- Claude through the Anthropic API with an API key, default model
  `claude-opus-5`; the project has no Amazon Bedrock access.
- Python, because the Temporal Python SDK is the only one with an official
  AgentCore sample and the Strands Agents plugin.
- OpenTofu for all infrastructure; AWS resources whenever they make sense;
  default region `ca-central-1`, configurable through `.env`.
- Latest stable versions, pinned by lock files.

**Why:** these follow from the demo goal (Temporal + AgentCore) and from the
accounts and access actually available.

**How to apply:** do not introduce Bedrock, Temporal API keys or another
language; keep versions current when adding dependencies.
