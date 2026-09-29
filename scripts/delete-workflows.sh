#!/usr/bin/env bash
# Deletes every closed workflow execution of the namespace (make
# delete-workflows):
#   1. count the closed executions;
#   2. delete them all with one server-side batch job;
#   3. wait for the job to finish and print its summary.
#
# The batch query leaves open executions (running or paused) out: a batch
# delete would otherwise terminate them first.
set -euo pipefail

source scripts/lib.sh

CLOSED_QUERY='ExecutionStatus != "Running" AND ExecutionStatus != "Paused"'
RUNNING_QUERY='ExecutionStatus = "Running"'
POLL_SECONDS=3

# count_workflows QUERY: prints how many executions match QUERY. The JSON
# output omits the count when it is zero.
count_workflows() {
  tcli workflow count --query "$1" -o json | jq -r '.count // "0"'
}

CLOSED=$(count_workflows "$CLOSED_QUERY")
if [[ "$CLOSED" -eq 0 ]]; then
  echo "Nothing to delete: no closed workflow."
  exit 0
fi

START_OUTPUT=$(tcli workflow delete --query "$CLOSED_QUERY" --reason "make delete-workflows" --yes)
JOB_ID=$(sed -n 's/^Started batch for job ID: //p' <<<"$START_OUTPUT")
[[ -n "$JOB_ID" ]] || die "No batch job ID in the temporal output: $START_OUTPUT"
echo "Deleting $CLOSED closed workflow(s) with batch job $JOB_ID..."

while true; do
  JOB=$(tcli batch describe --job-id "$JOB_ID" -o json)
  STATE=$(jq -r '.state' <<<"$JOB")
  [[ "$STATE" == BATCH_OPERATION_STATE_RUNNING ]] || break
  sleep "$POLL_SECONDS"
done

# Like the count, the JSON output omits every counter that is zero.
TOTAL=$(jq -r '.totalOperationCount // "0"' <<<"$JOB")
DELETED=$(jq -r '.completeOperationCount // "0"' <<<"$JOB")
FAILED=$(jq -r '.failureOperationCount // "0"' <<<"$JOB")
RUNNING=$(count_workflows "$RUNNING_QUERY")
echo "Deleted $DELETED/$TOTAL closed workflow(s), $FAILED failed; $RUNNING running workflow(s) left untouched."

[[ "$STATE" == BATCH_OPERATION_STATE_COMPLETED ]] || die "Batch job $JOB_ID ended in state $STATE."
[[ "$FAILED" -eq 0 ]]
