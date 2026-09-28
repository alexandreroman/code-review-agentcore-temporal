---
name: "Stack choices"
description: "Why the project uses mTLS, Claude on Amazon Bedrock and Python"
type: project
---

# Stack choices

- Temporal Cloud authenticates every client with mTLS certificates.
  Serverless Workers on AgentCore is a prerelease feature enabled on the
  namespace.
- Claude is reached only through Amazon Bedrock, authorized by the
  caller's IAM identity (the runtime role on AgentCore, the developer's
  credentials in the dev worker).
- Python: the Temporal Python SDK is the only one with an official
  AgentCore sample and the Strands Agents plugin.

**Why:** Bedrock and mTLS keep every credential inside AWS IAM and the
certificate pair, and Python gives the demo its AgentCore sample and agent
plugin.

**How to apply:** model access through Bedrock and IAM only, Temporal
access through mTLS only, orchestrator in Python.
