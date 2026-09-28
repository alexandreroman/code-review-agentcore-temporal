---
name: "Demo app is Java / Spring Boot"
description: "The reviewed demo repository is a Java / Spring Boot app; the orchestrator stays Python"
type: project
---

# Demo app is Java / Spring Boot

The demo repository `agentcore-review-demo-app`, whose pull requests the
agents review on stage, is a Java / Spring Boot application (Maven, Spring
Data JPA, H2, one flat package `com.example.orders`). The orchestrator in
this repository is a separate codebase and stays in Python (see
[Stack choices](project_stack.md)).

**Why:** Java is the most represented language in enterprise audiences, so
the reviewed code speaks to the people in the room.

**How to apply:** planted defects, `expected-findings.yaml` line ranges and
example paths in tool descriptions target Java files. The single flat
package keeps navigation within the agents' model call budget. A change to
the scenario moves the protected `baseline` / `scenario/*` tags on GitHub,
which needs admin bypass and a force-push.
