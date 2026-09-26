---
name: "Project title and code name"
description: "Where to use the display title and where to use the code name"
type: project
---

# Project title and code name

The project's display title is **Agentic Code Review with AgentCore x
Temporal**. It appears in human-facing documentation: README, CLAUDE.md
headings, specs, plans, slides.

The code name is **temporal-agentcore-review-demo**. It is used in code
(docstrings, comments, identifiers, package metadata), in the repository name
and in infrastructure names.

Component names follow their own, shorter convention: the deployable
components are `agentcore-review-demo-worker` and
`agentcore-review-demo-router`, the AgentCore runtime is
`agentcore_review_demo_worker` (AgentCore allows underscores only in this
name), and every Python package uses the `agentcore_review_` prefix. The
demo repository whose pull requests get reviewed is
`agentcore-review-demo-app`.

**Why:** the title reads well for an audience; the code name is the stable
technical identifier; component names stay short because AWS and AgentCore
enforce length limits on the identifiers built from them.

**How to apply:** use the title in prose written for people, the code name
everywhere in code and configuration, and the component names for the
specific resources and packages they label.
