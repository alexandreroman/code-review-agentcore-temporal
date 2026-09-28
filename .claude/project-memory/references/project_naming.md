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

The Python technical identifier is `agentcore_review`: every Python package
uses the `agentcore_review_` prefix (distributions use `agentcore-review-`).

Deployable components follow a shorter convention, the
`agentcore-review-demo` prefix (the `component_prefix` local of
`infra/aws/main.tf`). The AgentCore runtime name uses underscores instead
of hyphens, since AgentCore allows no hyphen in it.

The GitHub App name (the `GITHUB_APP_NAME` default in the Makefile) is the
one identifier that departs from the code name, because GitHub shows it to
people on pull requests. GitHub caps app names at 34 characters, and the
default name uses all 34.

**Why:** the title reads well for an audience; the code name is the stable
technical identifier; component names stay short because AWS and AgentCore
enforce length limits on the identifiers built from them; the GitHub App name
is read by people on every review.

**How to apply:** use the title in prose written for people, the code name
everywhere in code and configuration, the `agentcore_review` identifier for
Python packages, the component prefix for the specific resources and
packages it labels, and the GitHub App name wherever the app is named.
