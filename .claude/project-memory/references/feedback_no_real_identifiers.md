---
name: "Placeholders for account identifiers"
description: "Tracked files carry placeholders; real namespace, account and app IDs live in .env"
type: feedback
---

# Placeholders for account identifiers

Tracked files contain placeholders for every account-specific identifier:
Temporal Cloud namespace, AWS account IDs, GitHub owner, GitHub App ID or
slug. `.env.example` uses `your-namespace.a1b2c` for the namespace. The real
values live only in the git-ignored `.env`, in `certs/`, in the OpenTofu state
and in Secrets Manager. Code reads them from the environment with no real
default value.

**Why:** the repository is public for a conference demo; a real identifier in
a commit stays in the history.

**How to apply:** before every commit, check that the diff holds no real
identifier (`git grep` for the namespace name); make required settings fail
explicitly when unset instead of defaulting to a real value. A leak in an
unpushed commit is purged with `git filter-repo --replace-text`; a pushed
leak is reported to the user first.
