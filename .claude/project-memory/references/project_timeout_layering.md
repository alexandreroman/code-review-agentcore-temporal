---
name: "Timeout layering rule"
description: "Each timeout layer gives up before the one around it; a killed session costs about one 10 s heartbeat"
type: project
---

# Timeout layering rule

Each timeout layer gives up before the layer around it: client call <
activity attempt < child workflow run. Every activity heartbeats every 5 s
with a 10 s heartbeat timeout, so an activity cut off by a killed AgentCore
session costs about one heartbeat timeout and its start-to-close can be
sized for its worst case.

**Why:** an attempt that outlives its start-to-close keeps writing while
Temporal starts the next one; a task lost to a dead worker must not block
for a full start-to-close.

**How to apply:** check every new activity, client or timer against
`workflows/policies.py`; decorate every new activity with
`heartbeat_while_running`.
