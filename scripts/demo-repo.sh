# shellcheck shell=bash
# Fills, rebuilds and resets the demo repository $GITHUB_OWNER/$DEMO_REPO
# (sourced by scripts/github.sh and scripts/demo-reset.sh after scripts/lib.sh,
# not executed directly).
#
# The demo application lives in demo/, relative to the repository root the
# scripts run from: demo/baseline holds the starting state of the demo, and
# demo/customer-search.patch the change of the customer search scenario.

# Set by fill_demo_repo when it has pushed the demo application.
DEMO_REPO_FILLED=false

# build_demo_history DIR: builds the demo history from demo/ in the empty
# directory DIR: a commit of demo/baseline, tagged baseline, then a commit
# that applies demo/customer-search.patch, tagged scenario/customer-search.
# The tags are annotated, as the e2e checks expect (they read the peeled
# tags from git ls-remote). Everything is authored as $GITHUB_OWNER,
# whatever the local git configuration says.
build_demo_history() {
  local dir="$1"
  # git -C resolves a relative path from DIR, hence an absolute one.
  local patch="$PWD/demo/customer-search.patch"
  # A subshell, so that the identity stays out of the sourcing script.
  (
    export GIT_AUTHOR_NAME="$GITHUB_OWNER"
    export GIT_AUTHOR_EMAIL="$GITHUB_OWNER@users.noreply.github.com"
    export GIT_COMMITTER_NAME="$GIT_AUTHOR_NAME"
    export GIT_COMMITTER_EMAIL="$GIT_AUTHOR_EMAIL"

    git -C "$dir" init --quiet -b main
    # The trailing /. copies the dotfiles too; -p keeps mvnw executable.
    cp -Rp demo/baseline/. "$dir"
    git -C "$dir" add --all
    git -C "$dir" commit --quiet -m "Demo baseline: the order management API and its Reset demo workflow"
    git -C "$dir" tag -a baseline -m "Starting state of main for every demo"

    git -C "$dir" apply "$patch"
    git -C "$dir" add --all
    git -C "$dir" commit --quiet -m "Add customer search & order history"
    git -C "$dir" tag -a scenario/customer-search -m "Add customer search & order history"
  )
}

# push_demo_history DIR [--force]: pushes the history that build_demo_history
# built in DIR to the demo repository: main at the baseline tag, plus the
# baseline and scenario/customer-search tags. With --force, it overwrites
# whatever these refs point to.
push_demo_history() {
  local dir="$1"
  local force="${2:-}"
  git -C "$dir" push ${force:+"$force"} "https://github.com/$GITHUB_OWNER/$DEMO_REPO.git" \
    'baseline^{commit}:refs/heads/main' refs/tags/baseline refs/tags/scenario/customer-search
}

# fill_demo_repo: pushes the demo application from demo/ while the demo
# repository has no branch: main at the baseline tag, plus the baseline and
# scenario/customer-search tags. Once the repository has content, this does
# nothing, so a later make up never overwrites the demo.
fill_demo_repo() {
  local target="$GITHUB_OWNER/$DEMO_REPO"
  local branches
  branches=$(gh api "repos/$target/branches" --jq length)
  if [[ "$branches" -gt 0 ]]; then
    return
  fi

  echo "Pushing the demo application from demo/ into $target"
  local repo
  repo=$(mktemp -d)
  # A subshell, so that its EXIT trap removes the repository on every exit path.
  (
    trap 'rm -rf "$repo"' EXIT
    build_demo_history "$repo"
    push_demo_history "$repo"
  )
  # shellcheck disable=SC2034 # read by scripts/github.sh
  DEMO_REPO_FILLED=true
}

# rebuild_demo_repo: builds a new history from demo/ (new commits, even when
# demo/ is unchanged) and force-pushes it over the demo repository: main at
# the baseline tag, plus the baseline and scenario/customer-search tags. The
# scenario branches keep their old commits until reset_demo_repo recreates
# them. The rulesets on main and the tags let only an admin force-push (git
# then prints "Bypassed rule violations").
rebuild_demo_repo() {
  echo "Force-pushing a new history of the demo application from demo/ into $GITHUB_OWNER/$DEMO_REPO"
  local repo
  repo=$(mktemp -d)
  # A subshell, so that its EXIT trap removes the repository on every exit path.
  (
    trap 'rm -rf "$repo"' EXIT
    build_demo_history "$repo"
    push_demo_history "$repo" --force
  )
}

# latest_reset_run: prints the ID of the latest "Reset demo" run started by
# hand, or nothing when there is none.
latest_reset_run() {
  gh run list --workflow reset-demo.yml --repo "$GITHUB_OWNER/$DEMO_REPO" --event workflow_dispatch --limit 1 \
    --json databaseId --jq '.[0].databaseId // empty'
}

# reset_demo_repo: runs the "Reset demo" workflow, which creates the scenario
# branches, and waits for it to succeed.
reset_demo_repo() {
  local target="$GITHUB_OWNER/$DEMO_REPO"
  local manual_reset="gh workflow run reset-demo.yml --repo $target"
  local previous
  previous=$(latest_reset_run)
  gh workflow run reset-demo.yml --repo "$target" || die "The Reset demo workflow did not start: run $manual_reset"

  # The new run shows up in the list a few seconds after the dispatch.
  local run_id=""
  for _ in {1..10}; do
    sleep 3
    run_id=$(latest_reset_run)
    if [[ -n "$run_id" && "$run_id" != "$previous" ]]; then
      break
    fi
  done
  if [[ -z "$run_id" || "$run_id" == "$previous" ]]; then
    die "The Reset demo run never showed up in $target: run $manual_reset"
  fi

  local run_url="https://github.com/$target/actions/runs/$run_id"
  echo "Waiting for the Reset demo run: $run_url"
  gh run watch "$run_id" --repo "$target" --exit-status >/dev/null ||
    die "The Reset demo run failed: $run_url (once fixed, run $manual_reset)"
  echo "Demo repository $target reset: its scenario branches are ready."
}
