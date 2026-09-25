---
name: "Local dev uses Temporal Cloud"
description: "The local worker connects to Temporal Cloud; the project has no local Temporal server"
type: project
---

# Local dev uses Temporal Cloud

The local development worker connects to the Temporal Cloud namespace and
polls the `review-dev` task queue. The router sends pull requests opened from
a `dev/…` branch to that queue. The project has no Compose file and no local
Temporal dev server, even though skillbox conventions suggest one for
Temporal projects.

**Why:** real GitHub events and the real Lambda router are part of the loop;
only the task queue changes between development and production.

**How to apply:** `make dev` runs the local worker against Temporal Cloud; do
not add a `temporal server start-dev` service.
