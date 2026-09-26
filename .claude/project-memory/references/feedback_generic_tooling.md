---
name: "Generic tooling references"
description: "Code and docs name standard tools (docker), never the maintainer's machine specifics (podman)"
type: feedback
---

# Generic tooling references

Scripts, Makefile targets and docs call standard tools by their generic name:
`docker` to build, run and push containers. Machine-specific setups, such as
Podman behind a `docker` wrapper, never appear in the repository.

**Why:** the public repository must work for any reader with a Docker-compatible
CLI, not only on the maintainer's laptop.

**How to apply:** write `docker build --platform linux/arm64`, `docker push`,
and error messages such as "Docker is not running"; keep machine specifics out
of tracked files.
