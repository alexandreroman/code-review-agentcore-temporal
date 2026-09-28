#!/usr/bin/env bash
# Runs the local worker on the dev task queue, with hot reload (make dev).
#
# Exports the snapshots bucket from the aws stack outputs; the worker reads the
# GitHub App secret by name and calls Bedrock with the developer's AWS
# credentials.
set -euo pipefail

source scripts/lib.sh

bucket=$(aws_outputs | jq -r '.snapshots_bucket.value // empty')
[[ -n "$bucket" ]] || die "make dev: no snapshots bucket in the aws stack outputs (has make infra run?)"
export SNAPSHOTS_BUCKET="$bucket"

# info-panel.sh is best effort; it must never fail this target.
scripts/info-panel.sh --local-worker || true
trap 'scripts/info-panel.sh >/dev/null 2>&1 || true' EXIT

# Job control (`set -m`) puts the watchfiles job in its own process group, so a Ctrl-C on
# `make dev` (SIGINT to its own foreground group, which this script and make share) does not
# also land on watchfiles and the worker: only the trap below signals that group. Without this,
# both the terminal and the trap would signal watchfiles, racing its own shutdown and crashing
# it with a stray KeyboardInterrupt.
set -m
uv run watchfiles 'python -m agentcore_review_worker' worker/src shared/src &
child_pid=$!
set +m

# The trap only ever sends a signal and returns; it never blocks. Blocking on `wait` here, in the
# main flow rather than inside the trap, is what lets a second Ctrl-C interrupt that wait right
# away instead of queuing behind the trap that is already handling the first one.
stop_requests=0
stop() {
  stop_requests=$((stop_requests + 1))
  if [[ "$stop_requests" -ge 2 ]]; then
    kill -KILL -- "-$child_pid" 2>/dev/null || true
  else
    kill -TERM -- "-$child_pid" 2>/dev/null || true
  fi
}
trap stop INT TERM

child_status=0
while :; do
  if wait "$child_pid"; then
    child_status=0
  else
    child_status=$?
  fi
  kill -0 "$child_pid" 2>/dev/null || break
done

# A Ctrl-C, one or two, is not a failure: only report the worker's own exit code when it stopped
# on its own.
[[ "$stop_requests" -eq 0 ]] && exit "$child_status"
exit 0
