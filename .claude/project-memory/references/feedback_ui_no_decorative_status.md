---
name: "Web pages carry no decorative status indicators"
description: "No live badge, pulsing dot or refresh ping; state shows only when it needs attention"
type: feedback
---

# Web pages carry no decorative status indicators

The project's web pages (the router's status page, any mockup) show data
and nothing that merely signals liveness: no "live" badge, no pulsing
dot, no refresh ping. A state appears only when it needs the reader's
attention, for example an amber banner while the data cannot be fetched.
A plain "updated N s ago" line is enough to show freshness.

**Why:** the user reads such ornaments as AI slop that cheapens the page.

**How to apply:** when designing or reviewing a page, remove every
element whose only role is to look active; keep error and empty states,
shown only while they apply.
