---
name: "Casper stays out of user-facing files"
description: "README.md and .env.example never mention Casper or CASPER_PORT"
type: feedback
---

# Casper stays out of user-facing files

`README.md` and `.env.example` describe the project without any reference to
Casper, `CASPER_PORT` or `.casper.json`. Casper integration lives only in
`.casper.json`, the Makefile targets it calls, and internal design documents.

**Why:** Casper is the maintainer's personal workspace tool; readers of the
public repository do not need it to run the demo.

**How to apply:** describe ports, targets and settings by their own purpose;
keep Casper-specific explanations in Makefile comments or `.casper.json`.
