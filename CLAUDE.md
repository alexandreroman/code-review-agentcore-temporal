# Code Review with AgentCore x Temporal

AI agents review GitHub pull requests, orchestrated by Temporal and run as
Serverless Workers on Amazon Bedrock AgentCore.

See [README.md](README.md) for full documentation, [SETUP.md](SETUP.md)
for the installation and [DEMO.md](DEMO.md) for the demo run-through.

## Tech stack

- Python (uv workspace), Temporal Python SDK with the Strands Agents plugin
- Claude on Amazon Bedrock (Strands `BedrockModel`, Converse API)
- Temporal Cloud (mTLS), Amazon Bedrock AgentCore Runtime, AWS Lambda, S3
- OpenTofu for all infrastructure; GitHub App for PR integration

## Build & run

```bash
make install   # uv sync --all-packages
make check     # unit tests, ruff, OpenTofu fmt/validate
make dev       # local worker with hot reload (dev task queue)
make up        # deploy everything (AWS, worker, GitHub)
```

## Modules

- `shared/` — contract shared by the router and the worker
- `router/` — GitHub webhook handler and public status page (AWS Lambda)
- `worker/` — Temporal workflows, review agents, activities
- `tools/` — GitHub App registration tooling called by `scripts/github.sh`
- `infra/` — OpenTofu stacks (`bootstrap`, `aws`, `github`)
- `scripts/` — bash scripts behind the Make targets
- `demo/` — demo application (baseline and scenario patch) that `make up`
  pushes to the demo repository

## E2E validation

`/e2e-validation` (smoke) or `/e2e-validation full` validates the deployed
demo against real resources (`.claude/skills/e2e-validation/`): it opens
pull requests in the demo repository and spends Bedrock tokens, so run it
only when asked.

## Agents

Use the following agents (from the
[skillbox](https://github.com/alexandreroman/skillbox)
plugin) for all code tasks:

- **code-writer** — for ANY task that writes,
  modifies, or refactors code. This includes
  one-line fixes, import changes, visibility
  tweaks, and adding assertions. Never edit
  source files directly — always delegate to
  this agent.
- **code-reviewer** — for read-only code review
  before merging or when investigating issues.

## Memory

At the start of every conversation, read
`.claude/project-memory/MEMORY.md` to load
project context from previous conversations.

Use the **project-memory** skill (from the
[skillbox](https://github.com/alexandreroman/skillbox)
plugin) proactively — without being asked — whenever
the conversation reveals project decisions, deadlines,
team context, external references, workflow preferences,
or corrective feedback worth persisting across
conversations.

**Important:** Always use the **project-memory**
skill to persist information. Never use the built-in
auto-memory system (`~/.claude/projects/.../memory/`)
for project decisions or context — it is local and
not shared with the team.

## Conventions

- Line length limits for readability:
  - Text / Markdown: 80 columns max
  - Code: 120 columns max
- Follow standard Markdown conventions: blank line
  before and after headings, blank line before and
  after lists, fenced code blocks with a language tag
- Always use the latest LTS or stable version of
  languages, frameworks, and libraries. Check the
  official documentation or use available tools
  (e.g. context7) to verify current versions before
  choosing a dependency.
