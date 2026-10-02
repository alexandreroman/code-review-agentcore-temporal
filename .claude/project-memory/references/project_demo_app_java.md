---
name: "Demo app is Java / Spring Boot"
description: "The reviewed demo repository is a Java / Spring Boot app; the orchestrator is Python"
type: project
---

# Demo app is Java / Spring Boot

The demo repository `agentcore-review-demo-app`, whose pull requests the
agents review, is a Java / Spring Boot application in one flat package. The
orchestrator in this repository is a separate codebase in Python (see
[Stack choices](project_stack.md)).

**Why:** Java is the most represented language in enterprise audiences, so
the reviewed code speaks to the people in the room.

**How to apply:** planted defects, `expected-findings.yaml` line ranges and
example paths in tool descriptions target Java files. The single flat
package keeps navigation within the agents' model call budget. A scenario
change reaches GitHub through an empty demo repository (see
`demo/README.md`) or a [rebuild of its history](project_demo_repo_rebuild.md).
