---
name: "Public repository hygiene"
description: "Placeholders for account identifiers, generic tool names, Casper and internal login guidance confined to fixed places"
type: feedback
---

# Public repository hygiene

- Tracked files carry placeholders for every account-specific identifier:
  Temporal Cloud namespace (`your-namespace.a1b2c` in `.env.example`), AWS
  account IDs, GitHub App ID or slug, and the demo repository's owner,
  which no tracked file names. The real values live only in the
  git-ignored `.env`, in `certs/`, in the OpenTofu state and in Secrets
  Manager; code reads them from the environment with no real default. The
  CI badge and the skillbox links, which name this repository's owner,
  are fine.
- Scripts, Makefile targets and user-facing docs name standard tools
  generically: `docker` to build, run and push containers.
- Casper appears only in `.casper.json` and `scripts/info-panel.sh`; the
  Casper-only targets stay out of `make help` and of the docs.
- Internal AWS login guidance for Temporal employees (the `access` tool)
  appears only in `SETUP.md` §5.

**Why:** the repository is public: a real identifier in a commit stays in
the history, and readers need only a Docker-compatible CLI, not the
maintainer's personal tooling.

**How to apply:** before every commit, check that the diff holds no real
identifier (`git grep` for the namespace name); make required settings
fail explicitly when unset instead of defaulting to a real value; write
`docker build --platform linux/arm64` and messages such as "Docker is not
running". A leak in an unpushed commit is purged with
`git filter-repo --replace-text`; a pushed leak is reported to the user
first.
