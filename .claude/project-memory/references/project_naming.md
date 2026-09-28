---
name: "Project title and code name"
description: "Where to use the display title, the code name, the component names and the GitHub App name"
type: project
---

# Project title and code name

The project's display title is **Code Review with AgentCore x Temporal**.
It appears in human-facing documentation: README, CLAUDE.md headings, specs,
plans, slides.

The code name is **code-review-agentcore-temporal**. It is used in code
(docstrings, comments, identifiers, package metadata), in the repository name
and in infrastructure names.

Python packages use the `agentcore_review_` prefix; deployable components
use the shorter `agentcore-review-demo` prefix (with underscores in the
AgentCore runtime name). The GitHub App name is the one identifier that
departs from the code name, because people read it on pull requests.

**Why:** the title reads well for an audience and the code name is the
stable technical identifier; component names stay short because AWS and
AgentCore limit the length of the identifiers built from them.

**How to apply:** use the title in prose written for people, the code name
everywhere in code and configuration, the `agentcore_review` identifier for
Python packages, the component prefix for the specific resources and
packages it labels, and the GitHub App name wherever the app is named.
