#!/usr/bin/env bash
# Rebuilds the demo repository from demo/ with new commits (make demo-reset):
#   1. shows what the force-push overwrites and asks for confirmation (YES=1
#      skips it);
#   2. force-pushes a new history built from demo/: main at the baseline tag,
#      plus the baseline and scenario/customer-search tags;
#   3. runs the Reset demo workflow, which closes the open pull requests and
#      recreates the scenario branches from the new scenario tag;
#   4. checks that every ref landed on its tag.
# The new commits give the pull requests a clean slate: GitHub presents no
# earlier pull request on the "new pull request" page. They also ship any
# change made in demo/, which make up only pushes into an empty repository.
set -euo pipefail

source scripts/lib.sh
source scripts/demo-repo.sh

TARGET="$GITHUB_OWNER/$DEMO_REPO"
REMOTE="https://github.com/$TARGET.git"

# ref_sha REFS REF: prints the SHA of REF in REFS (the output of git
# ls-remote), or nothing when REF is missing.
ref_sha() {
  awk -v ref="$2" '$2 == ref { print $1 }' <<<"$1"
}

# A plain assignment, so that set -e stops here if the repository is missing.
BRANCHES=$(gh api "repos/$TARGET/branches" --jq length)
if [[ "$BRANCHES" -eq 0 ]]; then
  die "$TARGET has no branch: run make up instead, which fills an empty demo repository."
fi

REFS=$(git ls-remote "$REMOTE")
OPEN_PRS=$(gh pr list --repo "$TARGET" --state open --limit 100 --json number --jq length)

echo "This rebuilds $TARGET from demo/ with new commits and force-pushes it. Current state:"
echo "  main                      $(ref_sha "$REFS" refs/heads/main)"
echo "  baseline                  $(ref_sha "$REFS" 'refs/tags/baseline^{}')"
echo "  scenario/customer-search  $(ref_sha "$REFS" 'refs/tags/scenario/customer-search^{}')"
echo "  open pull requests        $OPEN_PRS (the Reset demo workflow closes them)"
echo "Any merge made on main since the last reset is lost."

if [[ "${YES:-}" != 1 ]]; then
  # The ! prefix of Claude Code, like any pipe, gives the script no terminal.
  if [[ ! -t 0 ]]; then
    die "No terminal to confirm on: rerun with YES=1 (YES=1 make demo-reset)."
  fi
  # An end of input (Ctrl-D) counts as a no.
  read -r -p "Overwrite $TARGET? [y/N] " answer || answer=""
  case "$answer" in
    y | Y | yes | Yes | YES) ;;
    *) die "Aborted: $TARGET is unchanged." ;;
  esac
fi

rebuild_demo_repo
reset_demo_repo

REFS=$(git ls-remote "$REMOTE")
BASELINE=$(ref_sha "$REFS" 'refs/tags/baseline^{}')
SCENARIO=$(ref_sha "$REFS" 'refs/tags/scenario/customer-search^{}')
if [[ -z "$BASELINE" || -z "$SCENARIO" ]]; then
  die "The baseline or scenario/customer-search tag is missing from $TARGET."
fi
if [[ "$(ref_sha "$REFS" refs/heads/main)" != "$BASELINE" ]]; then
  die "main is not on the baseline tag ($BASELINE) in $TARGET."
fi
for branch in feature/customer-search dev/customer-search; do
  if [[ "$(ref_sha "$REFS" "refs/heads/$branch")" != "$SCENARIO" ]]; then
    die "$branch is not on the scenario/customer-search tag ($SCENARIO) in $TARGET."
  fi
done
echo "Demo repository $TARGET rebuilt: main at ${BASELINE:0:7}, scenario branches at ${SCENARIO:0:7}."
