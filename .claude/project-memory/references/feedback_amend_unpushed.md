---
name: "Amend unpushed commits instead of stacking fixes"
description: "Fold a correction into the unpushed commit it corrects rather than adding a follow-up commit"
type: feedback
---

# Amend unpushed commits instead of stacking fixes

When a change corrects or partly reverts a recent commit that has not been
pushed, fold it into that commit (`git commit --amend` when it is HEAD, or a
soft reset and recommit for the last few local commits) instead of adding a
follow-up commit. The history then shows the intended change only, without a
change-then-revert pair.

**Why:** a clean, reviewable history matters for a public demo repository.

**How to apply:** before committing a fix, check whether its target commit is
local and unpushed; if so, amend it. Never rewrite commits that are pushed.
