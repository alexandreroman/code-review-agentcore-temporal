---
name: "Stack choices"
description: "Why the project uses mTLS, Claude on Amazon Bedrock and Python"
type: project
---

# Stack choices

- Temporal Cloud is authenticated with mTLS client certificates, not API
  keys. Serverless Workers on AgentCore is a prerelease feature enabled on
  the namespace.
- Claude is called through Amazon Bedrock with the Strands `BedrockModel`
  (Converse API), signed with the caller's AWS credentials: the runtime
  role on AgentCore, the developer's credentials in the dev worker. The
  project has no Anthropic API key and no direct Anthropic API client.
- Python, because the Temporal Python SDK is the only one with an official
  AgentCore sample and the Strands Agents plugin.

**Why:** these follow from the demo goal (Temporal + AgentCore) and from
the accounts and access actually available; Bedrock keeps every
credential inside AWS IAM.

**How to apply:** model access goes through Bedrock and IAM only; do not
introduce Temporal API keys or another language.
