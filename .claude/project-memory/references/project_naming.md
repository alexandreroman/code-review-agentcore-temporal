---
name: "Project title and code name"
description: "Where to use the display title and where to use the code name"
type: project
---

# Project title and code name

The project's display title is **Code Review with AgentCore x Temporal**.
It appears in human-facing documentation: README, CLAUDE.md headings, specs,
plans, slides.

The code name is **code-review-agentcore-temporal**. It is used in code
(docstrings, comments, identifiers, package metadata), in the repository name
and in infrastructure names.

The Python technical identifier is `agentcore_review`: every Python package
uses the `agentcore_review_` prefix (distributions use `agentcore-review-`).

Component names follow their own, shorter convention: the deployable
components are `agentcore-review-demo-worker` and
`agentcore-review-demo-router`, and the AgentCore runtime is
`agentcore_review_demo_worker` (AgentCore allows underscores only in this
name). The demo repository whose pull requests get reviewed is
`agentcore-review-demo-app`.

The GitHub App is named **Code Review w/AgentCore x Temporal** (slug
`code-review-w-agentcore-x-temporal`), the `GITHUB_APP_NAME` default in the
Makefile. It is the one identifier that departs from the code name, because
GitHub shows the app name to people on pull requests. GitHub caps app names
at 34 characters, and this one uses all 34.

**Why:** the title reads well for an audience; the code name is the stable
technical identifier; component names stay short because AWS and AgentCore
enforce length limits on the identifiers built from them; the GitHub App name
is read by people on every review.

**How to apply:** use the title in prose written for people, the code name
everywhere in code and configuration, the `agentcore_review` identifier for
Python packages, the component names for the specific resources and
packages they label, and the GitHub App name wherever the app is named.
