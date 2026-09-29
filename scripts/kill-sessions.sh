#!/usr/bin/env bash
# Stops every AgentCore session polling the production task queue (make
# kill-sessions), the same steps as the router's /kill command:
#   1. list the pollers of the task queue;
#   2. keep the agentcore:<endpoint>:<session> identities;
#   3. stop them all in parallel, retrying a transient ConflictException.
#
# Dead sessions stay listed for about 5 minutes after they stop, so a
# ResourceNotFoundException for one of them means "already gone", not a
# failure.
set -euo pipefail

source scripts/lib.sh

RUNTIME_ARN=$(jq -r '.runtime_arn.value // ""' <<<"$(aws_outputs)")
if [[ -z "$RUNTIME_ARN" ]]; then
  echo "No AgentCore runtime deployed: nothing to kill."
  exit 0
fi

IDENTITIES=$(
  tcli task-queue describe --task-queue "$TASK_QUEUE" -o json \
    | jq -r '[.. | objects | .identity? // empty | strings] | unique[] | select(startswith("agentcore:"))'
)

if [[ -z "$IDENTITIES" ]]; then
  echo "No active worker, nothing to kill."
  exit 0
fi

RESULTS_FILE=$(mktemp)
trap 'rm -f "$RESULTS_FILE"' EXIT

# stop_one IDENTITY: stops one session, printing "<identity> -> <outcome>"
# and appending the outcome's category (stopped, gone or failed) to
# RESULTS_FILE so the parent can build the summary.
stop_one() {
  local identity="$1" endpoint session_id attempt error_output code outcome
  endpoint="${identity#agentcore:}"
  endpoint="${endpoint%%:*}"
  session_id="${identity#agentcore:"$endpoint":}"

  for attempt in 1 2 3; do
    if error_output=$(aws bedrock-agentcore stop-runtime-session --agent-runtime-arn "$RUNTIME_ARN" \
      --runtime-session-id "$session_id" --qualifier "$endpoint" 2>&1 >/dev/null); then
      outcome=stopped
      break
    fi
    if [[ "$error_output" == *ResourceNotFoundException* ]]; then
      outcome=gone
      break
    fi
    if [[ ("$error_output" == *ConflictException* || "$error_output" == *ThrottlingException*) \
      && "$attempt" -lt 3 ]]; then
      sleep 1
      continue
    fi
    code=$(grep -oE '\([A-Za-z]+Exception\)' <<<"$error_output" | head -1 | tr -d '()')
    outcome="failed: ${code:-unknown error}"
    break
  done

  local display="$outcome"
  [[ "$outcome" == gone ]] && display="already gone"
  echo "$identity -> $display"
  echo "${outcome%%:*}" >>"$RESULTS_FILE"
}
export -f stop_one
export RUNTIME_ARN RESULTS_FILE

printf '%s\n' "$IDENTITIES" | xargs -P 8 -I{} bash -c 'stop_one "$@"' _ {}

STOPPED=$(grep -c '^stopped$' "$RESULTS_FILE" || true)
GONE=$(grep -c '^gone$' "$RESULTS_FILE" || true)
FAILED=$(grep -c '^failed$' "$RESULTS_FILE" || true)
echo "Stopped $STOPPED AgentCore session(s), $GONE already gone, $FAILED failed."
[[ "$FAILED" -eq 0 ]]
