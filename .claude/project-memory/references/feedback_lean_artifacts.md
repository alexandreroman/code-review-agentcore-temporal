---
name: "Lean, optimized artifacts"
description: "Plans favour small, fast deliverables with few moving parts"
type: feedback
---

# Lean, optimized artifacts

Plans and generated code aim for lean deliverables: the smallest reasonable
Lambda package and container image, fast cold starts, few moving parts.
Build artifacts are optimized from the first version (multi-stage images,
no bundling of what the runtime already provides).

**Why:** the demo is often deployed from conference networks with slow
uplinks; bloated artifacts cost time and teach nothing.

**How to apply:** when writing a plan, size every artifact that crosses the
network and state how it is kept small; question every file and step that
does not serve the demo.
