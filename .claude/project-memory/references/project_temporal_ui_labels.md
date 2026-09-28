---
name: "Temporal UI labels and details"
description: "Activity type names are short labels; summaries and static details carry only the per-call detail"
type: project
---

# Temporal UI labels and details

Every activity type name is a short PascalCase label, and the Python
function behind it carries the same name in snake_case (`ListFiles` is
`list_files`, `ClosePR` is `close_pr`, `Read` is `read`). The activity
`summary`, and a child workflow's `static_summary`, hold only the detail
of the call and never repeat the label. A child workflow's
`static_details` is short Markdown. Neither ever shows file contents or
comment bodies.

**Why:** on stage the audience reads the Temporal UI Timeline; a short
label plus a precise detail shows what each agent does at a glance, and
a name read in the UI leads straight to its code.

**How to apply:** every new activity follows this convention. Summary
builders fed with model arguments never raise. Renaming an activity type
breaks the replay of unversioned in-flight `make dev` workflows, which
then need terminating.
