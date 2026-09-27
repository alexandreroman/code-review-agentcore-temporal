---
name: "Stack choices"
description: "Why the project uses mTLS, the Anthropic API and Python"
type: project
---

# Stack choices

- Temporal Cloud is authenticated with mTLS client certificates, not API
  keys. Serverless Workers on AgentCore is a prerelease feature enabled on
  the namespace.
- Claude is called through the Anthropic API with an API key: the project
  has no Amazon Bedrock access.
- Python, because the Temporal Python SDK is the only one with an official
  AgentCore sample and the Strands Agents plugin.

**Why:** these follow from the demo goal (Temporal + AgentCore) and from
the accounts and access actually available.

**How to apply:** do not introduce Bedrock, Temporal API keys or another
language.
