---
name: "No maintainer specifics in public files"
description: "Public files name generic tools (docker) and never mention Casper or other personal setups"
type: feedback
---

# No maintainer specifics in public files

Scripts, Makefile targets and user-facing docs (README, SETUP, DEMO,
`.env.example`, script messages) name standard tools generically: `docker`
to build, run and push containers. They never mention machine-specific
setups (Podman behind a `docker` wrapper) nor Casper, `CASPER_PORT`,
`.casper.json` or the Casper-only targets (`worktree-init`,
`info-publish`). Casper details live only in `.casper.json`, Makefile
comments and `scripts/info-panel.sh`.

**Why:** the repository is public; readers need only a Docker-compatible
CLI to run the demo, not the maintainer's personal tooling.

**How to apply:** write `docker build --platform linux/arm64` and error
messages such as "Docker is not running"; describe ports, targets and
settings by their own purpose.
