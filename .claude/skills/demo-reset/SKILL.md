---
name: demo-reset
description: >-
  Rebuilds the demo repository of Code Review with AgentCore x Temporal
  from demo/ with new commits and resets it (make demo-reset): ships a
  change of demo/ and gives pull requests a clean slate. It force-pushes
  main and the demo tags and closes the open pull requests.
disable-model-invocation: true
---

# Demo reset

`make demo-reset` rebuilds the demo repository's history from `demo/` with
new commits, force-pushes `main` (at `baseline`) and the `baseline` and
`scenario/customer-search` tags, then runs the **Reset demo** workflow,
which closes the open pull requests and recreates the scenario branches.
GitHub then presents no earlier pull request on the "new pull request"
page.

Side effects, to recall in the report:

- `main` loses any merge made during a demo or an e2e run;
- the open pull requests get closed;
- the commit SHAs change on every run, even when `demo/` is unchanged.

Run every block with the Bash tool, from the repository root.

## 1. Preconditions

```bash
gh auth status
REPO="$(make -s print-GITHUB_OWNER)/$(make -s print-DEMO_REPO)"
echo "$REPO"
gh api "repos/$REPO" --jq .permissions.admin
```

Stop and report when `gh` is not logged in or the last line is not `true`:
only an admin bypasses the `main` and `tags` rulesets for the force-push.

## 2. Run

Claude Code's auto mode refuses force-pushes, so ask the human to run, in
this session:

```text
! YES=1 make demo-reset
```

`YES=1` is required: the `!` prefix gives the script no terminal to
confirm on. Then wait for the human to say it ran. If it failed, report
its error and stop.

When the settings (`.claude/settings.json`, `.claude/settings.local.json`
or `~/.claude/settings.json`) hold a `Bash(make demo-reset*)` allow rule,
run it yourself instead, with a 600000 ms timeout:

```bash
make demo-reset YES=1
```

(`YES=1` comes after the target, so that the command matches the rule.)

## 3. Verify

```bash
bash <<'CHECK'
REPO="$(make -s print-GITHUB_OWNER)/$(make -s print-DEMO_REPO)"
refs=$(git ls-remote "https://github.com/$REPO.git") || exit 1
sha() { awk -v ref="$1" '$2 == ref { print $1 }' <<<"$refs"; }
base=$(sha 'refs/tags/baseline^{}')
scenario=$(sha 'refs/tags/scenario/customer-search^{}')
echo "baseline: $base"
echo "scenario/customer-search: $scenario"
check() { if [[ -n "$2" && "$(sha "refs/heads/$1")" == "$2" ]]; then echo "$1 OK"; else echo "$1 FAIL"; fi; }
check main "$base"
check feature/customer-search "$scenario"
check dev/customer-search "$scenario"
echo "open pull requests: $(gh pr list -R "$REPO" --state open --json number --jq length)"
CHECK
```

Every branch must be `OK` and no pull request may be open.

## 4. Report

A short summary: the new SHAs of `baseline` and `scenario/customer-search`
(short form), the number of pull requests closed (the "open pull requests"
line `make demo-reset` printed before the push), any failed check, and the
side effects listed above.
