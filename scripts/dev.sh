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

# Not exec'd, so that the EXIT trap still runs once the worker stops.
uv run watchfiles 'python -m agentcore_review_worker' worker/src shared/src
