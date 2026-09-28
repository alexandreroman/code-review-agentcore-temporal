---
name: "Temporal UI labels and details"
description: "Activity type names are short labels; summaries and static details carry only the per-call detail"
type: project
---

# Temporal UI labels and details

Each activity type name is a short PascalCase label, and its Python
function has the same name in snake_case (`ListFiles` is `list_files`).
Summaries and details follow the `summaries.py` docstring.

**Why:** on stage the audience reads the Temporal UI Timeline; a short
label plus a precise detail shows what each agent does at a glance, and
a name read in the UI leads straight to its code.

**How to apply:** every new activity follows this convention. Summary
builders fed with model arguments never raise. Renaming an activity type
breaks the replay of unversioned in-flight `make dev` workflows, which
then need terminating.
