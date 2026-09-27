---
name: e2e-validation
description: >-
  End-to-end validation of Agentic Code Review with AgentCore x Temporal
  against the real AWS, Temporal Cloud and GitHub resources. Mode smoke
  (default, 6 to 8 min) after a change to the worker, the router or the
  infrastructure; mode full (about 30 min) before a conference. It opens,
  comments on and merges pull requests in the demo repository and spends
  Anthropic tokens.
argument-hint: "[smoke|full]"
disable-model-invocation: true
---

# E2E validation

Mode requested: `$ARGUMENTS`. `full` selects the full mode (before a talk);
anything else, or nothing, selects `smoke` (after a change).

| Mode    | Target       | Steps, in run order                                 |
| ------- | ------------ | --------------------------------------------------- |
| `smoke` | 6 to 8 min   | P-0, Setup, 01-06, Report                           |
| `full`  | About 30 min | P-0, Setup, 01-06, reset, 04 x2, 06b, 07-09, Report |

The smoke run walks one pull request through its whole life: opened
(E2E-01), `/kill` during the review (E2E-02), round published (E2E-03),
defects found (E2E-04), `/fix` (E2E-05), merge (E2E-06).

## Rules

- Run every block with the Bash tool, from the repository root, exactly as
  written. Each block is a `bash` script fed by a `<<'STEP'` heredoc that
  sources `helpers.sh` first: shell state does not survive between
  commands, so settings come from the Makefile and run state from
  `/tmp/e2e-validation/current/state.env`.
- Set the Bash tool timeout given in each step heading (600000 ms for the
  steps that wait for a review).
- Run the steps in order and do not add retries: `tcli` already retries the
  Temporal CLI (5 attempts; the Go CLI fails intermittently on unstable
  networks), and every wait polls every 5 s up to the step's maximum.
- A failing check records `FAIL`, runs `collect` (histories of the step's
  workflows, task queue, router and worker logs, pull request) into
  `/tmp/e2e-validation/current/failure/`, and the run goes on, unless the
  step says **Stop**. A step whose precondition failed is recorded with
  `result <step> FAIL "skipped: <reason>"`.
- Never run `temporal workflow query` (it wakes an AgentCore worker and
  spoils E2E-09), `make deploy`, `make destroy`, or a push to the demo
  repository. The only writes allowed: the Reset demo workflow, pull
  requests, comments, merges and closes in the demo repository, and
  `make kill-sessions`.
- When a precondition needs the human (expired AWS SSO session, `gh`
  login, nothing deployed), stop and tell them the command to run.

## P-0 — Preconditions (timeout 180000)

Requires: `make up` has run, the demo repository holds `baseline` and
`scenario/customer-search`, AWS credentials, `gh` logged in with write
access to the demo repository, the mTLS certificate of `.env`.

```bash
bash <<'STEP'
source .claude/skills/e2e-validation/helpers.sh
new_run
save MODE "$([[ "$ARGUMENTS" == full ]] && echo full || echo smoke)"
save RUN_START "$(now)"
fail=0
check() {
  local label="$1"
  shift
  if "$@" >/dev/null 2>&1; then echo "ok: $label"; else echo "MISSING: $label"; fail=1; fi
}
for tool in gh temporal aws jq tofu uvx git; do check "$tool on PATH" command -v "$tool"; done
check "AWS credentials (aws sso login)" aws sts get-caller-identity
check "gh logged in (gh auth login)" gh auth status
check "push access on $REPO" test "$(gh api "repos/$REPO" --jq .permissions.push)" = true
check "Temporal Cloud reachable over mTLS" tcli workflow list --limit 1
check "Reset demo workflow active" test "$(gh api "repos/$REPO/actions/workflows/reset-demo.yml" --jq .state)" = active
outputs=$(tofu -chdir=infra/aws output -json 2>/dev/null || echo '{}')
save BUILD "$(jq -r '.current_build.value // ""' <<<"$outputs")"
save RUNTIME_ID "$(jq -r '.runtime_id.value // ""' <<<"$outputs")"
save BUCKET "$(jq -r '.snapshots_bucket.value // ""' <<<"$outputs")"
save ROUTER_LOG_GROUP "$(jq -r '.router_log_group.value // ""' <<<"$outputs")"
check "a deployed build (make up)" test -n "$BUILD"
version=$(tcli worker deployment describe-version --deployment-name "$DEPLOYMENT" --build-id "$BUILD" -o json \
  2>/dev/null || echo '{}')
check "$BUILD is the current version and serves $TASK_QUEUE (make deploy)" jq -e --arg q "$TASK_QUEUE" \
  '(.currentSinceTime // "") as $t | $t != "" and ($t | startswith("1970") | not)
   and ([.taskQueuesInfos[]?.name] | index($q) != null)' <<<"$version"
uvx --from pyyaml==6.0.3 python -c 'import json, sys, yaml; json.dump(yaml.safe_load(sys.stdin), sys.stdout)' \
  <"$SKILL_DIR/expected-findings.yaml" >"$E2E_DIR/expected.json"
check "expected findings" jq -e '.defects | length == 3' "$E2E_DIR/expected.json"
if [[ "$fail" == 0 ]]; then result Preconditions ok "build $BUILD"; else result Preconditions FAIL "see MISSING"; fi
exit "$fail"
STEP
```

Success: exit 0, no `MISSING` line. **Stop** on failure: report the missing
items to the human (AWS: `aws sso login`; `gh auth login`; nothing
deployed: `make up`).

## Setup — Reset and return to zero (timeout 600000)

Requires P-0. The full mode runs this block again as "Reset between runs".

```bash
bash <<'STEP'
source .claude/skills/e2e-validation/helpers.sh
label=${1:-Setup}
t0=$SECONDS
if reset_and_wait 120 "$TASK_QUEUE" && make_retry kill-sessions \
  && agentcore_pollers "$E2E_DIR/pollers-before.json"; then
  result "$label" ok "reset, workflows closed and sessions stopped in $((SECONDS - t0))s"
else
  result "$label" FAIL "see the output above"
  collect
  exit 1
fi
STEP
```

Success: the reset run succeeded, no PR is open, no `PullRequestWorkflow`
runs on the production queue, `main` is on `baseline` and both scenario
branches on `scenario/customer-search`, `make kill-sessions` exited 0.
**Stop** on failure.

## E2E-01 — Scale-from-zero (timeout 180000)

Requires Setup. Opens the pull request from `feature/customer-search`.

```bash
bash <<'STEP'
source .claude/skills/e2e-validation/helpers.sh
opened=$(now)
PR=$(open_pr feature/customer-search "$SCENARIO_TITLE") || { result E2E-01 FAIL "gh pr create failed"; exit 1; }
save PR "$PR"
save WF "$(pr_workflow_id "$PR")"
echo "PR #$PR, workflow $WF"
wf_started() { describe "$WF"; }
first_activity() {
  local file
  file=$(fetch_history "$WF") || return 1
  jqe -e 'include "e2e"; (workflow_tasks | length) > 0 and (activities | length) > 0' "$file"
}
if ! wait_until 30 "workflow started" wf_started; then
  result E2E-01 FAIL "no workflow $WF 30 s after the PR (webhook, router)"
  collect "$WF"
  exit 1
fi
wait_until 60 "first activity scheduled" first_activity
jqe --slurpfile before "$E2E_DIR/pollers-before.json" --argjson opened "$opened" 'include "e2e";
  started_at as $t0 | workflow_tasks[0] as $w | ([activities[].scheduled] | min) as $a
  | {identity: $w.identity,
     webhook_s: ($t0 - $opened | round),
     cold_start_s: (if $w then ($w.t - $t0) * 10 | round / 10 else null end),
     first_activity_s: (if $a then ($a - $t0) * 10 | round / 10 else null end),
     new_session: (($w.identity // "" | startswith("agentcore:")) and ($before[0] | index($w.identity) | not))}' \
  "$E2E_DIR/history/$WF.json" >"$E2E_DIR/e2e-01.json"
cat "$E2E_DIR/e2e-01.json"
save COLD_START_S "$(jq -r '.cold_start_s // "none"' "$E2E_DIR/e2e-01.json")"
if jq -e '.new_session and .cold_start_s <= 30 and .first_activity_s != null' "$E2E_DIR/e2e-01.json" >/dev/null; then
  result E2E-01 ok "new session, first workflow task ${COLD_START_S}s after the start"
else
  result E2E-01 FAIL "$(jq -c . "$E2E_DIR/e2e-01.json")"
  collect "$WF"
fi
STEP
```

Success: the first workflow task runs on an `agentcore:` identity absent
from the pollers listed after `make kill-sessions` (`DescribeTaskQueue`
keeps dead sessions for about 5 minutes, so "no poller" means "no live
one"), at most 30 s after the execution started, and an activity is
scheduled. **Stop** if no workflow started.

## E2E-02 — `/kill` during the review (timeout 300000)

Requires E2E-01. Waits until a reviewer has finished one activity and runs
another, then kills every session of the production queue. E2E-03 records
the verdict once the round is published.

```bash
bash <<'STEP'
source .claude/skills/e2e-validation/helpers.sh
mid_flight() {
  local c file
  for c in $CATEGORIES; do
    describe "$WF-r1-$c" 2>/dev/null | jq -e '(.pendingActivities // []) | length > 0' >/dev/null || continue
    file=$(fetch_history "$WF-r1-$c") || continue
    jq -e '[.events[] | select(.activityTaskCompletedEventAttributes)] | length > 0' "$file" >/dev/null && return 0
  done
  return 1
}
if ! wait_until 150 "a reviewer finished one activity and runs another" mid_flight; then
  result E2E-02 FAIL "no reviewer reached the middle of its loop"
  collect "$WF" "$WF-r1-security" "$WF-r1-performance" "$WF-r1-maintainability"
  exit 1
fi
agentcore_pollers "$E2E_DIR/pollers-at-kill.json"
url=$(gh pr comment "$PR" -R "$REPO" --body "/kill") || { result E2E-02 FAIL "gh pr comment failed"; exit 1; }
save KILL_AT "$(now)"
echo "/kill posted: $url"
confirmed() { [[ "$(bot_comments "$PR" '[1-9][0-9]* AgentCore sessions? stopped')" -ge 1 ]]; }
if wait_until 60 "bot confirms the stopped sessions" confirmed; then
  save KILL_CONFIRMED yes
else
  save KILL_CONFIRMED no
fi
STEP
```

## E2E-03 — Review round under 3 minutes (timeout 600000)

Requires E2E-01. Records the E2E-02 verdict first when `/kill` was posted.

```bash
bash <<'STEP'
source .claude/skills/e2e-validation/helpers.sh
round1=("$WF" "$WF-r1-security" "$WF-r1-performance" "$WF-r1-maintainability" "$WF-r1-synthesis")
if ! wait_until 360 "round 1 published" round_published "$WF" 1; then
  if [[ -n "${KILL_AT:-}" ]]; then result E2E-02 FAIL "skipped: round 1 not published"; fi
  result E2E-03 FAIL "round 1 not published 6 min after the PR"
  for step in E2E-04 E2E-05 E2E-06; do result "$step" FAIL "skipped: round 1 not published"; done
  collect "${round1[@]}"
  exit 1
fi

# E2E-02 verdict: resumption without replay.
if [[ -n "${KILL_AT:-}" ]]; then
  killed=$(jq -cs 'add | unique' "$E2E_DIR/pollers-before.json" "$E2E_DIR/pollers-at-kill.json")
  report="$E2E_DIR/e2e-02.json"
  for wf in "${round1[@]}"; do
    file=$(fetch_history "$wf") || continue
    jqe -c --argjson kill "$KILL_AT" --argjson killed "$killed" \
      'include "e2e"; kill_report($kill) + {resumed: resumed_starts($killed)}' "$file"
  done | jq -s --argjson kill "$KILL_AT" '{
    finished_before: (map(.finished_before) | add),
    retried_before: (map(.retried_before) | add),
    interrupted: (map(.interrupted) | add),
    resume_s: ((map(.resumed[]) | min) as $m | if $m then ($m - $kill) * 10 | round / 10 else null end)}' >"$report"
  cat "$report"
  save RESUME_S "$(jq -r '.resume_s // "none"' "$report")"
  if jq -e '.retried_before == 0 and .interrupted >= 1 and .resume_s != null' "$report" >/dev/null \
    && [[ "${KILL_CONFIRMED:-no}" == yes ]]; then
    kept=$(jq -r '"\(.finished_before) finished activities kept attempt 1, \(.interrupted) retried"' "$report")
    result E2E-02 ok "$kept, resumed ${RESUME_S}s after /kill"
  else
    result E2E-02 FAIL "$(jq -c . "$report"), confirmation comment: ${KILL_CONFIRMED:-no}"
    collect "${round1[@]}"
  fi
fi

# E2E-03 verdict.
save ROUND1_S "$(jqe 'include "e2e"; check_updates[1] - started_at | round' "$E2E_DIR/history/$WF.json")"
conclusion=$(check_conclusion "$(head_sha "$PR")")
reviews=$(gh api "repos/$REPO/pulls/$PR/reviews?per_page=100" \
  --jq '[.[] | select(.user.type == "Bot" and .state == "COMMENTED")] | length')
if [[ "$ROUND1_S" -le 180 && "$conclusion" == failure && "$reviews" == 1 ]]; then
  result E2E-03 ok "round 1 in ${ROUND1_S}s (kill included), one review, AI Review red"
else
  result E2E-03 FAIL "round 1 in ${ROUND1_S}s, $reviews review(s), AI Review $conclusion"
  collect "$WF"
fi
STEP
```

Success for E2E-02: the bot confirmed the stopped sessions; every activity
completed before the kill needed one attempt; at least one activity
scheduled before the kill was retried (attempt 2 or more), on a session
that was not killed.

Success for E2E-03: from the execution start to the second `set_check`
completion (the round's conclusion) takes at most 180 s, the bot published
exactly one `COMMENTED` review, and `AI Review` is `failure` (the SQL
injection is at least `high`).

**Stop** if the round never finishes (the block records E2E-04 to E2E-06
as skipped): go to the report.

## E2E-04 — Planted defects found (timeout 120000)

Requires E2E-03. In the full mode, the label becomes `E2E-04 run 2` and
`E2E-04 run 3` (see below).

```bash
bash <<'STEP'
source .claude/skills/e2e-validation/helpers.sh
check_coverage "E2E-04"
STEP
```

Matching rules: header of `expected-findings.yaml`. The reviewer workflow
IDs (`$WF-r1-<category>`) assume one batch per category: true for the demo
scenario (well under 15 files / 60,000 bytes), but a larger diff would add
a `-b<n>` suffix.

Success: every defect found. On failure the step prints every finding: a
finding on the right function just outside the range means line drift in
the demo repository (compare with the tag), otherwise a reviewer missed it.

## E2E-05 — `/fix` (timeout 600000)

Requires E2E-03 with a red check.

```bash
bash <<'STEP'
source .claude/skills/e2e-validation/helpers.sh
fail() { result E2E-05 FAIL "$1"; collect "$WF" "$WF-fix1"; exit 1; }
save FIX_AT "$(now)"
url=$(gh pr comment "$PR" -R "$REPO" --body "/fix") || fail "gh pr comment failed"
cid=${url##*issuecomment-}
eyes() {
  [[ "$(gh api "repos/$REPO/issues/comments/$cid/reactions" --jq 'map(.content) | index("eyes") != null')" == true ]]
}
fix_commits() {
  gh api "repos/$REPO/pulls/$PR/commits?per_page=100" \
    --jq "[.[] | select(.commit.message | contains(\"Review-Fix: $WF/\"))]"
}
pushed() { [[ "$(fix_commits | jq length)" -ge 1 ]]; }
wait_until 30 "eyes reaction on /fix" eyes || fail "no eyes reaction on the /fix comment"
wait_until 360 "fix commit pushed" pushed || fail "no Review-Fix commit 6 min after /fix"
commits=$(fix_commits)
fix_sha=$(jq -r '.[0].sha' <<<"$commits")
green() { [[ "$(check_conclusion "$fix_sha")" == success ]]; }
wait_until 300 "AI Review green on the fix commit" green || fail "AI Review is $(check_conclusion "$fix_sha")"
save FIX_TO_GREEN_S "$(($(now) - FIX_AT))"
count=$(jq length <<<"$commits")
verified=$(jq -r '.[0].commit.verification.verified' <<<"$commits")
resolved=$(review_threads "$PR" | jq '[.[] | select(.resolved)] | length')
if [[ "$count" == 1 && "$verified" == true && "$resolved" -ge 1 && "$(head_sha "$PR")" == "$fix_sha" ]]; then
  result E2E-05 ok "1 verified commit, AI Review green ${FIX_TO_GREEN_S}s after /fix, $resolved thread(s) resolved"
else
  fail "$count fix commit(s), verified=$verified, $resolved thread(s) resolved"
fi
STEP
```

Success: 👀 (`eyes`) on the `/fix` comment; exactly one commit carrying the
`Review-Fix: <workflow id>/<n>` trailer, verified by GitHub, and it is the
head of the PR; `AI Review` is `success` on it; at least one review thread
resolved.

## E2E-06 — Merge with a green check (timeout 300000)

Requires E2E-05. If E2E-05 failed, run only this block, which closes the
PR:

```bash
bash <<'STEP'
source .claude/skills/e2e-validation/helpers.sh
gh pr close "$PR" -R "$REPO"
result E2E-06 FAIL "skipped: E2E-05 failed"
STEP
```

Otherwise:

```bash
bash <<'STEP'
source .claude/skills/e2e-validation/helpers.sh
merge() { gh pr merge "$PR" -R "$REPO" --merge; }
completed() { workflow_completed "$WF"; }
# Retried: GitHub may take a few seconds to see the green check.
wait_until 30 "PR merged" merge || { result E2E-06 FAIL "gh pr merge refused"; collect "$WF"; exit 1; }
wait_until 120 "workflow completed" completed || { result E2E-06 FAIL "workflow still open"; collect "$WF"; exit 1; }
outcome=$(jqe -c 'include "e2e"; result_with(["merged", "rounds"])' "$(fetch_history "$WF")")
threads=$(review_threads "$PR")
keys=$(aws s3api list-objects-v2 --bucket "$BUCKET" --prefix "$(lower "$OWNER")/$(lower "$DEMO_REPO")/pr-$PR/" \
  --query 'length(Contents || `[]`)' --output text)
login=$(gh api user --jq .login)
echo "outcome: $outcome"
echo "threads: $threads"
echo "snapshot objects left: $keys"
if jq -e --arg login "$login" --argjson threads "$threads" '
    (.open_findings | map(.id)) as $open
    | .merged and ((.closed_by // "") | ascii_downcase) == ($login | ascii_downcase) and .rounds >= 2
      and ([.open_findings[] | select(.severity == "critical" or .severity == "high")] | length) == 0
      and all($threads[]; .resolved == (.id as $i | $open | index($i) | not))' <<<"$outcome" >/dev/null \
  && [[ "$keys" == 0 ]]; then
  result E2E-06 ok "merged by $login after $(jq -r .rounds <<<"$outcome") rounds, snapshots deleted"
else
  result E2E-06 FAIL "outcome $outcome, $keys snapshot object(s) left"
  collect "$WF"
fi
STEP
```

Success: `gh pr merge` (no `--admin`) succeeds; the workflow completes; its
`PullRequestOutcome` says merged, by the `gh` user, at least 2 rounds, no
open `critical`/`high` finding; every thread of a finding still open is
unresolved and every other thread resolved; the PR's snapshot prefix
`<owner>/<repo>/pr-<n>/` in the snapshots bucket is empty.

**End of the smoke mode**: go to the report.

## Full mode

Run after the smoke steps, in this order.

### Reset between runs (timeout 600000)

The smoke merge moved `main` and deleted `feature/customer-search`: run the
Setup block again with the label as argument, its first line becoming
`bash -s -- "Reset between runs" <<'STEP'`.

### E2E-04 runs 2 and 3 (timeout 600000 each)

Run the block as written (run 2), then again with `3` as argument, its
first line becoming `bash -s -- 3 <<'STEP'`. Run 2 closes its PR; run 3
keeps it open for E2E-06b.

```bash
bash -s -- 2 <<'STEP'
source .claude/skills/e2e-validation/helpers.sh
RUN=${1:?run number}
PR=$(open_pr feature/customer-search "$SCENARIO_TITLE (run $RUN)") \
  || { result "E2E-04 run $RUN" FAIL "gh pr create failed"; exit 1; }
save PR "$PR"
save WF "$(pr_workflow_id "$PR")"
if wait_until 360 "round 1 published" round_published "$WF" 1; then
  check_coverage "E2E-04 run $RUN"
else
  result "E2E-04 run $RUN" FAIL "round 1 not published 6 min after the PR"
  collect "$WF"
fi
if [[ "$RUN" == 2 ]]; then
  gh pr close "$PR" -R "$REPO"
  wait_until 120 "workflow of PR #$PR closed" workflow_closed "$WF" || echo "workflow $WF still open" >&2
fi
STEP
```

Success: as E2E-04, on each run. Smoke's E2E-04 counts as run 1: the
defects must be found on 3 consecutive runs.

### E2E-06b — Admin merge with a red check (timeout 300000)

Requires E2E-04 run 3 (PR open, check red, no `/fix`).

```bash
bash <<'STEP'
source .claude/skills/e2e-validation/helpers.sh
fail() { result E2E-06b FAIL "$1"; collect "$WF"; exit 1; }
[[ "$(check_conclusion "$(head_sha "$PR")")" == failure ]] || fail "AI Review is not red on PR #$PR"
gh pr merge "$PR" -R "$REPO" --admin --merge || fail "admin merge refused"
completed() { workflow_completed "$WF"; }
wait_until 120 "workflow completed" completed || fail "workflow still open"
file=$(fetch_history "$WF")
save LAST_PROD_AT "$(jqe 'include "e2e"; .events[-1].eventTime | ts | floor' "$file")"
outcome=$(jqe -c 'include "e2e"; result_with(["merged", "rounds"])' "$file")
closing=$(bot_comments "$PR" "<!-- closing:$WF -->")
login=$(gh api user --jq .login)
echo "outcome: $outcome"
echo "closing comments: $closing"
if jq -e --arg login "$login" '.merged and ((.closed_by // "") | ascii_downcase) == ($login | ascii_downcase)
    and ([.open_findings[] | select(.severity == "critical" or .severity == "high")] | length) >= 1' \
    <<<"$outcome" >/dev/null && [[ "$closing" == 1 ]]; then
  open=$(jq '.open_findings | length' <<<"$outcome")
  result E2E-06b ok "bypass by $login traced with $open open finding(s), one closing comment"
else
  fail "outcome $outcome, $closing closing comment(s)"
fi
STEP
```

Success: the admin merge succeeds; the outcome records the merge by the
`gh` user with at least one open blocking finding; exactly one bot comment
carries `<!-- closing:<workflow id> -->`. The completion time is the start
of the E2E-09 clock: no production workflow runs after it.

### E2E-07 — Dev mode (timeout 600000)

1. Start the local worker with the Bash tool's `run_in_background` option
   (keep the task ID to stop it later):

   ```bash
   make dev >/tmp/e2e-validation/current/dev-worker.log 2>&1
   ```

2. Run:

```bash
bash <<'STEP'
source .claude/skills/e2e-validation/helpers.sh
fail() { result E2E-07 FAIL "$1"; collect ${DEV_WF:+"$DEV_WF"}; exit 1; }
ready() { grep -q "polling $DEV_TASK_QUEUE" "$E2E_DIR/dev-worker.log"; }
wait_until 120 "local worker polling $DEV_TASK_QUEUE" ready || fail "local worker not polling (dev-worker.log)"
PR=$(open_pr dev/customer-search "$SCENARIO_TITLE (dev)") || fail "gh pr create failed"
save PR "$PR"
save DEV_WF "$(pr_workflow_id "$PR")"
first_task() {
  local file
  file=$(fetch_history "$DEV_WF") || return 1
  jqe -e 'include "e2e"; (workflow_tasks | length) > 0' "$file"
}
wait_until 60 "dev workflow picked up" first_task || fail "no workflow task for the dev PR"
queue=$(describe "$DEV_WF" | jq -r '.executionConfig.taskQueue.name')
identity=$(jqe -r 'include "e2e"; workflow_tasks[0].identity' "$E2E_DIR/history/$DEV_WF.json")
gh pr comment "$PR" -R "$REPO" --body "/kill" >/dev/null || fail "gh pr comment failed"
dev_reply() { [[ "$(bot_comments "$PR" 'Ctrl-C')" -ge 1 ]]; }
wait_until 60 "dev /kill reply" dev_reply
reply=$?
wait_until 360 "dev round 1 published" round_published "$DEV_WF" 1
round=$?
if [[ "$queue" == "$DEV_TASK_QUEUE" && "$identity" == dev:* && "$reply" == 0 && "$round" == 0 ]]; then
  result E2E-07 ok "handled by $identity on $queue, /kill answered with the dev message"
else
  fail "queue $queue, identity $identity, /kill reply $reply, round $round"
fi
STEP
```

Success: the workflow runs on `review-dev`, its first workflow task on a
`dev:` identity, `/kill` gets the "Ctrl-C is your friend" reply and no
session is stopped, the round is published by the local worker. Keep the
local worker and the PR: E2E-08 closes it.

### E2E-08 — Reset (timeout 600000)

Requires the local worker still running (it finishes the dev workflow when
the reset closes its PR).

```bash
bash <<'STEP'
source .claude/skills/e2e-validation/helpers.sh
t0=$SECONDS
if reset_and_wait 180 "$TASK_QUEUE" "$DEV_TASK_QUEUE"; then
  result E2E-08 ok "reset in $((SECONDS - t0))s: no open PR, no running workflow, refs on their tags"
else
  result E2E-08 FAIL "see the output above"
  collect ${DEV_WF:+"$DEV_WF"}
fi
STEP
```

Success: the run succeeds, no PR is open, no `PullRequestWorkflow` runs on
either queue, `main` is on `baseline` and both branches on the scenario tag.

Then stop the local worker: stop its background task, then run:

```bash
bash <<'STEP'
pkill -TERM -f agentcore_review_worker 2>/dev/null
sleep 2
if pgrep -fl agentcore_review_worker; then echo "local worker still running"; exit 1; fi
echo "local worker stopped"
STEP
```

### E2E-09 — Back to zero, no idle cost (timeout 600000)

Requires E2E-06b (`LAST_PROD_AT`).

```bash
bash <<'STEP'
source .claude/skills/e2e-validation/helpers.sh
deadline=$((LAST_PROD_AT + 60 + IDLE_TIMEOUT + 30))
pause=$((deadline + 60 - $(now)))
if ((pause > 0)); then
  echo "waiting ${pause}s: drain 60 s + idle timeout ${IDLE_TIMEOUT} s + margins"
  sleep "$pause"
fi
group="/aws/bedrock-agentcore/runtimes/$RUNTIME_ID-$BUILD"
last_log=$(aws logs filter-log-events --log-group-name "$group" --start-time "$((LAST_PROD_AT * 1000))" \
  --query 'max(events[].timestamp)' --output text)
drained=$(aws logs filter-log-events --log-group-name "$group" --start-time "$((LAST_PROD_AT * 1000))" \
  --filter-pattern '"drained"' --query 'max(events[].timestamp)' --output text)
late=$(aws logs filter-log-events --log-group-name "$group" --start-time "$((deadline * 1000))" \
  --query 'length(events)' --output text)
last_poll=$(tcli task-queue describe --task-queue "$TASK_QUEUE" -o json \
  | jqe 'include "e2e"; agentcore_last_poll // 0 | floor')
after() { [[ "$1" =~ ^[0-9]+$ ]] && echo "+$(($1 / 1000 - LAST_PROD_AT))s" || echo none; }
echo "last runtime log $(after "$last_log"), drained $(after "$drained"), events after the deadline: $late"
if [[ "$late" == 0 && "$last_poll" -le $((LAST_PROD_AT + 135)) ]]; then
  result E2E-09 ok "last log $(after "$last_log"), drained $(after "$drained"), no poll after +135s"
else
  msg="$late log event(s) after +$((deadline - LAST_PROD_AT))s, last poll +$((last_poll - LAST_PROD_AT))s"
  result E2E-09 FAIL "$msg"
  collect
fi
STEP
```

Success: no runtime log event later than the last production activity +
60 s (drain) + `AGENTCORE_IDLE_TIMEOUT` + 30 s, and no AgentCore poll later
than the last activity + 60 s (drain) + 75 s (one long poll). The poller
list of `DescribeTaskQueue` keeps sessions for about 5 minutes, so only the
poll timestamps count.

## Report (timeout 60000)

```bash
bash <<'STEP'
source .claude/skills/e2e-validation/helpers.sh
total=$(($(now) - RUN_START))
{
  echo "# E2E validation, $MODE mode, $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo
  echo "Build $BUILD, repository $REPO, total $((total / 60)) min $((total % 60)) s."
  echo
  echo "| Step | Result | Measured |"
  echo "|---|---|---|"
  awk -F '\t' '{ printf "| %s | %s | %s |\n", $1, ($2 == "ok" ? "✅" : "❌"), $3 }' "$E2E_DIR/results.tsv"
  echo
  echo "- Cold start (workflow start to first workflow task): ${COLD_START_S:-n/a} s"
  echo "- Round 1 (start to AI Review conclusion): ${ROUND1_S:-n/a} s"
  echo "- Resumption after /kill: ${RESUME_S:-n/a} s"
  echo "- /fix to green check: ${FIX_TO_GREEN_S:-n/a} s"
  if [[ -d "$E2E_DIR/failure" ]]; then
    echo
    echo "Collected on failure, in $E2E_DIR/failure:"
    ls "$E2E_DIR/failure" | sed 's/^/- /'
  fi
} | tee "$E2E_DIR/report.md"
STEP
```

Show the report to the human as is. Nothing needs cleaning up: sessions
drain by themselves, and the next run's Setup resets the demo repository
(run `make kill-sessions` to stop sessions right away).

## Troubleshooting

| Symptom                    | Where to look                                |
| -------------------------- | -------------------------------------------- |
| Every `tcli` attempt fails | Unstable network (Go CLI): use a stable one  |
| No workflow after the PR   | `webhook-deliveries.log` has no line for it  |
| Webhook status 401         | Webhook secret of the app vs Secrets Manager |
| Webhook status 500         | `router.log`: Temporal error of the router   |
| Workflow started, no task  | Current version, queue attachment            |
| E2E-04 misses a defect     | Printed findings: line drift or a real miss  |
| No fix commit              | Fixer history; "branch changed" comment      |

A delivery that never reached the router appears in the app's settings
(Advanced, Recent Deliveries); ask the human to redeliver it there.
