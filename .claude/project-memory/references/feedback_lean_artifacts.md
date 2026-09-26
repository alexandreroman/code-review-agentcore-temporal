---
name: "Lean, optimized artifacts over ceremony"
description: "Plans favour small, fast deliverables and skip ceremony such as infrastructure tests"
type: feedback
---

# Lean, optimized artifacts over ceremony

Plans and generated code aim for lean deliverables: the smallest reasonable
Lambda package and container image, fast cold starts, few moving parts. Build
artifacts are optimized from the first version (multi-stage images, no
bundling of what the runtime already provides) rather than after a slow
deploy reveals the cost. Ceremony that does not serve the demo, such as unit
tests for infrastructure or tooling, is left out (see
[[feedback-tests-business-only]]).

**Why:** the project is a demonstrative, teaching-oriented demo, often deployed
from conference networks with slow uplinks; bloated artifacts and needless
tests cost time and teach nothing.

**How to apply:** when writing a plan, size every artifact that crosses the
network and state how it is kept small; question every test, file and step
that does not serve the demo or the core review logic.
