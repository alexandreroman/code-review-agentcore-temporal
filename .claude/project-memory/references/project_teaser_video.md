---
name: "Teaser video"
description: "Remotion teaser: source and spec git-ignored under docs/, only assets/app-overview.mp4 committed"
type: project
---

# Teaser video

`assets/app-overview.mp4` is an animated teaser of the AgentCore x
Temporal integration, generated with Remotion. The source project lives in
`docs/video/` and the spec in
`docs/superpowers/specs/2026-09-29-teaser-video-design.md`, both
git-ignored; only the rendered MP4 is committed.

**Why:** a short video for social feeds and the repository page that
shows why the integration matters, without screen captures that depend
on a live deployment.

**How to apply:** every label in the video mirrors the real system but
never a timing value, so tuning timeouts, retries or the drain delay
leaves the video accurate; when a mirrored label changes in the code,
re-render the teaser from `docs/video/` and commit the new MP4.
