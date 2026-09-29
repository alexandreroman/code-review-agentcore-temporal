---
name: "Timeout layering rule"
description: "Each timeout layer gives up before the one around it; a killed session costs about one 10 s heartbeat"
type: project
---

# Timeout layering rule

Timers and timeouts follow one rule: each layer gives up before the layer
around it, and an activity cut off by a killed AgentCore session (`/kill`,
maximum lifetime, deploy) costs about one heartbeat timeout, whatever the
activity.

- A client call gives up inside its activity attempt: Bedrock read timeout
  under the model activity's start-to-close; the worker's GitHub client at
  10 s under every GitHub activity.
- An activity that can run longer than a few seconds heartbeats every 5 s
  (`activities/heartbeats.py`) with a 10 s heartbeat timeout, so its
  start-to-close can be sized for the worst case of its sequential calls.
- Short single-call activities have no heartbeat and a start-to-close that
  fits their calls plus the 1 s write spacing.
- Child workflows time out after their activities: `CHILD_RUN_TIMEOUT`
  covers `HARD_TURN_LIMIT` model calls plus one recovery.

**Why:** a `/kill` exposed tasks lost to a dead worker's open polls, each
one blocked for a full timeout; an attempt that outlives its start-to-close
keeps writing while Temporal starts the next one.

**How to apply:** when adding or changing an activity, a client or a
timer, check it against the layer around it (`workflows/policies.py`) and
give any multi-call or slow activity the 5 s / 10 s heartbeat.
