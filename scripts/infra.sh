#!/usr/bin/env bash
# Applies the aws stack (make infra, make deploy, make prune).
#
# Usage: scripts/infra.sh [BUILD_ID] [DROP...]
#
# BUILD_ID becomes the deployed build (the current one when omitted). Every
# other endpoint is kept, except the DROP names: the endpoints a pinned
# workflow still needs live only in the stack outputs, so keeping them alive
# means re-reading those outputs before every apply and passing them back.
set -euo pipefail

source scripts/lib.sh

require_cloudflare

BUILD_ID="${1:-}"
if [[ $# -gt 0 ]]; then
  shift
fi

OUTPUTS=$(aws_outputs)
if [[ -z "$BUILD_ID" ]]; then
  BUILD_ID=$(jq -r '.current_build.value // ""' <<<"$OUTPUTS")
fi

DROP=$(jq -nc '$ARGS.positional' --args "$@")
RETAINED=$(jq -c --arg build "$BUILD_ID" --argjson drop "$DROP" '
  (.endpoints.value // {})
  | with_entries(select(.key != $build and (.key | IN($drop[]) | not)))
  | map_values(.version)
' <<<"$OUTPUTS")

TF_VAR_build_id="$BUILD_ID" TF_VAR_retained_endpoints="$RETAINED" \
  tofu -chdir="$AWS_STACK" apply -input=false -auto-approve
