# Demo application

The Java application whose pull requests the review agents work on. It
does not run in this project: `make up` pushes it into the demo repository
(`<owner>/agentcore-review-demo-app` unless `DEMO_REPO` says otherwise).

## Contents

- `baseline/`: the order management API (Spring Boot), in the state `main`
  starts every demo from, with its **Reset demo** workflow.
- `customer-search.patch`: the "Add customer search & order history"
  scenario, a change with planted defects for the reviewers to find. The
  defects are listed in
  [`expected-findings.yaml`](../.claude/skills/e2e-validation/expected-findings.yaml).

## How it reaches the demo repository

[`scripts/demo-repo.sh`](../scripts/demo-repo.sh) builds a fresh history
from this folder: a commit of the content of `baseline/`, tagged
`baseline`, then a commit that applies `customer-search.patch`, tagged
`scenario/customer-search`. It pushes `main` at `baseline` and both tags.
The **Reset demo** workflow then creates the `feature/customer-search` and
`dev/customer-search` branches from the scenario tag.

Only the content of `baseline/` and the patch are pushed: this README
stays in this repository.

## Changing the demo

- `make up` pushes the demo only into an empty demo repository; it never
  overwrites one that already has content.
- The patch must apply cleanly on `baseline/` (`git apply`).
- The line numbers of `expected-findings.yaml` refer to the files at the
  scenario tag: update them whenever the patch changes.
