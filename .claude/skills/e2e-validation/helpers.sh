# Helpers of the e2e-validation skill (sourced, never executed).
#
# Every step of SKILL.md runs in its own `bash` block, fed by a `<<'STEP'`
# heredoc, that sources this file first: agent shells keep no state between
# commands, so the settings are re-read from the Makefile (which applies
# .env and its defaults) and the run state from $E2E_DIR/state.env.
#
# No `set -e`: a failed check must still reach its `result` line.
# Compatible with bash 3.2 (macOS /bin/bash).
set -uo pipefail

cd "$(git rev-parse --show-toplevel)" || exit 1

SKILL_DIR=.claude/skills/e2e-validation
E2E_ROOT=/tmp/e2e-validation
POLL=5
CATEGORIES="security performance maintainability"
SCENARIO_TITLE="Add customer search & order history"
# Seconds before AgentCore ends an idle session, as set in infra/aws/worker.tf.
IDLE_TIMEOUT=120

{
  read -r TEMPORAL_NAMESPACE
  read -r TEMPORAL_ADDRESS
  read -r TLS_CERT
  read -r TLS_KEY
  read -r AWS_REGION
  read -r TASK_QUEUE
  read -r DEV_TASK_QUEUE
  read -r DEPLOYMENT
  read -r PR_IDLE_WARNING
  read -r DEMO_REPO
  read -r OWNER
} < <(make -s print-TEMPORAL_NAMESPACE print-TEMPORAL_ADDRESS print-TEMPORAL_TLS_CERT_PATH \
  print-TEMPORAL_TLS_KEY_PATH print-AWS_REGION print-TASK_QUEUE print-DEV_TASK_QUEUE \
  print-TEMPORAL_DEPLOYMENT_NAME print-PR_IDLE_WARNING_SECONDS print-DEMO_REPO print-GITHUB_OWNER)
export TEMPORAL_NAMESPACE TEMPORAL_ADDRESS AWS_REGION
export AWS_DEFAULT_REGION="$AWS_REGION"
# tofu output needs it: the aws stack's state encryption reads var.region.
export TF_VAR_region="$AWS_REGION"
REPO="$OWNER/$DEMO_REPO"

if [[ -L "$E2E_ROOT/current" ]]; then
  E2E_DIR=$(cd "$E2E_ROOT/current" && pwd -P)
  # shellcheck source=/dev/null
  source "$E2E_DIR/state.env"
fi

# --- Run state and report ---------------------------------------------------

# new_run: creates a run directory and points $E2E_ROOT/current at it.
new_run() {
  E2E_DIR="$E2E_ROOT/$(date -u +%Y%m%dT%H%M%SZ)"
  mkdir -p "$E2E_DIR/history"
  ln -sfn "$E2E_DIR" "$E2E_ROOT/current"
  : >"$E2E_DIR/state.env"
  : >"$E2E_DIR/results.tsv"
  echo "Run directory: $E2E_DIR"
}

# save NAME VALUE: keeps a value for this step and the next ones.
save() {
  printf '%s=%q\n' "$1" "$2" >>"$E2E_DIR/state.env"
  printf -v "$1" '%s' "$2"
}

# result STEP ok|FAIL DETAIL: records one line of the final report.
result() {
  printf '%s\t%s\t%s\n' "$1" "$2" "$3" >>"$E2E_DIR/results.tsv"
  echo "$1: $2 - $3"
}

now() { date -u +%s; }
lower() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]'; }

# jqe ARGS...: jq with e2e.jq on the module path (filters start with `include "e2e";`).
jqe() { jq -L "$SKILL_DIR" "$@"; }

# wait_until MAX_SECONDS LABEL COMMAND...: runs COMMAND in this shell every
# $POLL seconds until it succeeds, then prints "LABEL: <n>s". Prints a
# TIMEOUT line on stderr and returns 1 after MAX_SECONDS.
wait_until() {
  local max="$1" label="$2" start=$SECONDS
  shift 2
  until "$@" >/dev/null 2>&1; do
    if ((SECONDS - start >= max)); then
      echo "TIMEOUT after ${max}s: $label" >&2
      return 1
    fi
    sleep "$POLL"
  done
  echo "$label: $((SECONDS - start))s"
}

# make_retry TARGET: make targets that call the temporal CLI get 3 attempts.
make_retry() {
  local attempt
  for attempt in 1 2 3; do
    make -s "$1" && return 0
    echo "make $1: attempt $attempt/3 failed" >&2
    [[ "$attempt" -lt 3 ]] && sleep 5
  done
  return 1
}

# --- Temporal -----------------------------------------------------------------

# tcli ARGS...: the temporal CLI with explicit mTLS flags (it ignores the TLS
# environment variables) and up to 5 attempts, 3 s apart: the Go CLI fails
# intermittently on unstable networks ("context deadline exceeded", TLS EOF)
# while the service is healthy. "not found" is an answer, never retried.
tcli() {
  local attempt err out
  err=$(mktemp)
  for attempt in 1 2 3 4 5; do
    if out=$(temporal "$@" --tls-cert-path "$TLS_CERT" --tls-key-path "$TLS_KEY" \
      --client-connect-timeout 15s --command-timeout 30s 2>"$err"); then
      rm -f "$err"
      printf '%s\n' "$out"
      return 0
    fi
    grep -qi 'not found' "$err" && break
    echo "temporal $1 ${2:-}: attempt $attempt/5 failed: $(tail -n 1 "$err")" >&2
    [[ "$attempt" -lt 5 ]] && sleep 3
  done
  cat "$err" >&2
  rm -f "$err"
  return 1
}

describe() { tcli workflow describe -w "$1" -o json; }

# fetch_history WORKFLOW_ID: saves the event history under $E2E_DIR/history and prints its path.
fetch_history() {
  local file="$E2E_DIR/history/$1.json"
  tcli workflow show -w "$1" -o json >"$file" || return 1
  echo "$file"
}

pr_workflow_id() { echo "pr-$(lower "$OWNER")-$(lower "$DEMO_REPO")-$1"; }

# running_pr_workflows QUEUE: number of running PullRequestWorkflow executions on QUEUE.
running_pr_workflows() {
  tcli workflow count -o json \
    -q "WorkflowType = 'PullRequestWorkflow' AND ExecutionStatus = 'Running' AND TaskQueue = '$1'" |
    jq -r '(.count // 0) | tonumber'
}

# agentcore_pollers FILE: saves the AgentCore identities listed on the production queue.
agentcore_pollers() {
  tcli task-queue describe --task-queue "$TASK_QUEUE" -o json |
    jqe 'include "e2e"; agentcore_identities' >"$1"
}

# round_published WORKFLOW_ID ROUND: the parent completed 2 x ROUND UpdateCheck activities.
round_published() {
  local file
  file=$(fetch_history "$1") || return 1
  jqe -e --argjson n "$2" 'include "e2e"; (check_updates | length) >= 2 * $n' "$file" >/dev/null
}

workflow_completed() {
  describe "$1" | jq -e '.workflowExecutionInfo.status | ascii_downcase | test("completed")' >/dev/null
}

# --- GitHub -------------------------------------------------------------------

head_sha() { gh pr view "$1" -R "$REPO" --json headRefOid --jq .headRefOid; }

# check_conclusion SHA: conclusion of the AI Review check on SHA ("pending" while it runs).
check_conclusion() {
  gh api "repos/$REPO/commits/$1/check-runs?check_name=AI%20Review" --jq '.check_runs[0].conclusion // "pending"'
}

# bot_comments PR REGEX: number of bot comments on the PR whose body matches REGEX.
bot_comments() {
  gh api "repos/$REPO/issues/$1/comments?per_page=100" \
    --jq "[.[] | select(.user.type == \"Bot\" and (.body | test(\"$2\")))] | length"
}

# open_pr BRANCH TITLE: opens a pull request from BRANCH and prints its number.
open_pr() {
  local url
  url=$(gh pr create -R "$REPO" --base main --head "$1" --title "$2" \
    --body "E2E validation run $(basename "$E2E_DIR").") || return 1
  echo "${url##*/}"
}

# review_threads PR: [{id: "S-01", resolved: true|false}] for every thread carrying a finding marker.
review_threads() {
  gh api graphql -F owner="$OWNER" -F name="$DEMO_REPO" -F number="$1" -f query='
    query($owner: String!, $name: String!, $number: Int!) {
      repository(owner: $owner, name: $name) {
        pullRequest(number: $number) {
          reviewThreads(first: 100) { nodes { isResolved comments(first: 1) { nodes { body } } } }
        }
      }
    }' --jq '[.data.repository.pullRequest.reviewThreads.nodes[]
      | {id: ([.comments.nodes[0].body | match("<!-- finding:([SPM]-[0-9]+) -->").captures[0].string] | first),
         resolved: .isResolved}
      | select(.id)]'
}

# reset_demo: dispatches the "Reset demo" workflow and waits (max 180 s) for a successful run.
reset_demo() {
  local t0 run=""
  t0=$(now)
  gh workflow run reset-demo.yml -R "$REPO" --ref main || return 1
  _reset_registered() {
    run=$(gh run list -R "$REPO" --workflow reset-demo.yml --event workflow_dispatch --limit 5 \
      --json databaseId,createdAt \
      --jq "[.[] | select((.createdAt | fromdateiso8601) >= $((t0 - 10)))][0].databaseId // empty")
    [[ -n "$run" ]]
  }
  _reset_finished() { [[ "$(gh run view "$run" -R "$REPO" --json status --jq .status)" == completed ]]; }
  wait_until 30 "reset run registered" _reset_registered || return 1
  wait_until 180 "reset run $run finished" _reset_finished || return 1
  if [[ "$(gh run view "$run" -R "$REPO" --json conclusion --jq .conclusion)" != success ]]; then
    echo "reset run $run failed: gh run view $run -R $REPO --log-failed" >&2
    return 1
  fi
}

# demo_refs_ok: main is on the baseline tag, both scenario branches on scenario/customer-search.
demo_refs_ok() {
  local refs base scenario
  refs=$(git ls-remote "https://github.com/$REPO.git") || return 1
  _ref() { awk -v ref="$1" '$2 == ref { print $1 }' <<<"$refs"; }
  base=$(_ref 'refs/tags/baseline^{}')
  scenario=$(_ref 'refs/tags/scenario/customer-search^{}')
  [[ -n "$base" && -n "$scenario" ]] || { echo "tag baseline or scenario/customer-search missing" >&2; return 1; }
  [[ "$(_ref refs/heads/main)" == "$base" ]] || { echo "main is not on baseline" >&2; return 1; }
  [[ "$(_ref refs/heads/feature/customer-search)" == "$scenario" ]] ||
    { echo "feature/customer-search is not on scenario/customer-search" >&2; return 1; }
  [[ "$(_ref refs/heads/dev/customer-search)" == "$scenario" ]] ||
    { echo "dev/customer-search is not on scenario/customer-search" >&2; return 1; }
}

# reset_and_wait MAX_SECONDS QUEUE...: resets the demo repository, then checks
# that no pull request is open, that no PullRequestWorkflow runs on any QUEUE
# (waiting up to MAX_SECONDS) and that the refs are back on their tags.
reset_and_wait() {
  local max="$1" open
  shift
  local queues="$*"
  _no_pr_workflow() {
    local queue
    for queue in $queues; do
      [[ "$(running_pr_workflows "$queue")" == 0 ]] || return 1
    done
  }
  reset_demo || return 1
  open=$(gh pr list -R "$REPO" --state open --json number --jq length) || return 1
  [[ "$open" == 0 ]] || { echo "$open pull request(s) still open after the reset" >&2; return 1; }
  wait_until "$max" "PR workflows closed on $queues" _no_pr_workflow || return 1
  demo_refs_ok
}

# --- Checks shared by several steps --------------------------------------------

# check_coverage LABEL: E2E-04 on the round 1 reviewers of $WF, against expected-findings.yaml.
check_coverage() {
  local c file findings="$E2E_DIR/findings-$PR.json" coverage="$E2E_DIR/coverage-$PR.json"
  for c in $CATEGORIES; do
    file=$(fetch_history "$WF-r1-$c") || continue
    jqe 'include "e2e"; result_with(["findings", "resolved_ids"]).findings // []' "$file"
  done | jq -s 'add // []' >"$findings"
  jqe --slurpfile f "$findings" 'include "e2e"; coverage($f[0])' "$E2E_DIR/expected.json" >"$coverage"
  jq -c '.[]' "$coverage"
  if jq -e 'all(.found)' "$coverage" >/dev/null; then
    result "$1" ok "PR #$PR: $(jq -r 'map(.id) | join(", ")' "$coverage") found"
  else
    result "$1" FAIL "PR #$PR missed $(jq -r 'map(select(.found | not) | .id) | join(", ")' "$coverage")"
    jq -c '.[] | {category, path, line, end_line, title}' "$findings"
    collect "$WF-r1-security" "$WF-r1-performance" "$WF-r1-maintainability"
  fi
}

# collect WORKFLOW_ID...: gathers what a failed step needs into $E2E_DIR/failure.
collect() {
  local dir="$E2E_DIR/failure" wf
  mkdir -p "$dir"
  for wf in "$@"; do
    tcli workflow show -w "$wf" -o json >"$dir/history-$wf.json" 2>&1
    tcli workflow describe -w "$wf" -o json >"$dir/describe-$wf.json" 2>&1
  done
  tcli task-queue describe --task-queue "$TASK_QUEUE" -o json >"$dir/task-queue.json" 2>&1
  aws logs tail "$ROUTER_LOG_GROUP" --since 30m --format short >"$dir/router.log" 2>&1
  grep -i webhook "$dir/router.log" >"$dir/webhook-deliveries.log"
  if [[ -n "${RUNTIME_ID:-}" ]]; then
    aws logs tail "/aws/bedrock-agentcore/runtimes/$RUNTIME_ID-$BUILD" --since 30m --format short \
      >"$dir/worker.log" 2>&1
  fi
  if [[ -n "${PR:-}" ]]; then
    gh pr view "$PR" -R "$REPO" --json number,state,headRefOid,commits,reviews,comments >"$dir/pr-$PR.json" 2>&1
    gh api "repos/$REPO/commits/$(head_sha "$PR")/check-runs" >"$dir/check-runs-$PR.json" 2>&1
  fi
  echo "Collected into $dir"
}
