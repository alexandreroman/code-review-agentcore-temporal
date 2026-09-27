---
name: "Local dev uses Temporal Cloud"
description: "The project has no local Temporal server; make dev runs against Temporal Cloud"
type: project
---

# Local dev uses Temporal Cloud

The project has no Compose file and no local Temporal dev server: `make dev`
runs the local worker against the Temporal Cloud namespace, on the dev task
queue, even though skillbox conventions suggest a local server for Temporal
projects.

**Why:** real GitHub events and the real Lambda router are part of the
loop; only the task queue differs between development and production.

**How to apply:** do not add a `temporal server start-dev` service.
