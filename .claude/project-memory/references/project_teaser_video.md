---
name: "Teaser video"
description: "Animated Remotion teaser of the integration; source in git-ignored docs/video/, output assets/app-overview.mp4"
type: project
---

# Teaser video

`assets/app-overview.mp4` is a 78-second animated teaser (1920x1080, 30 fps,
silent, English captions) of the AgentCore x Temporal integration, told
through the pull request review use case. Its lead message is scale from
zero; Strands agents as Temporal activities and durability (`/kill`, the
review resumes on a new session) support it. It sits on the temporal.io
background (`#141414` under the ultraviolet grid) with Noto Sans Mono
labels and Inter captions; each technology wears its own colors: Temporal
ultraviolet and purple, AWS category colors on squid ink (Lambda orange,
AgentCore and Bedrock teal, IAM red), GitHub's dark palette. No label
shows a specific duration: no heartbeat timeout, no idle drain delay, no
resume delay after `/kill`.

Remotion generates it. The source project lives in `docs/video/` and the
spec in `docs/superpowers/specs/2026-09-29-teaser-video-design.md`, both
git-ignored; only the rendered MP4 is committed.

**Why:** a short, silent-first video for social feeds and the repository
page that shows why the integration matters, without screen captures that
depend on a live deployment.

**How to apply:** every label in the video mirrors the real system
(workflow IDs, `Glob`/`Grep`/`Read` activities, demo application files
and planted defects) but never a timing value, so tuning timeouts, retries
or the drain delay leaves the video accurate; when one of the mirrored
labels changes in the code, re-render the teaser from `docs/video/`
(`docs/video/README.md`) and commit the new MP4.
