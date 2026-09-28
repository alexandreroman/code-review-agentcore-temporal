#!/usr/bin/env bash
# Removes the endpoints (and Temporal versions) of builds no pinned
# workflow still uses (make prune).
#
# An endpoint is prunable when its Worker Deployment Version is gone or
# fully drained. The current build is never touched; a Temporal error stops
# the script rather than dropping an endpoint a pinned workflow may need.
set -euo pipefail

source scripts/lib.sh

OUTPUTS=$(aws_outputs)
CURRENT_BUILD=$(jq -r '.current_build.value // ""' <<<"$OUTPUTS")

PRUNABLE=() # endpoints to drop
DRAINED=()  # existing drained versions to delete
while IFS= read -r name; do
  [[ -n "$name" && "$name" != "$CURRENT_BUILD" ]] || continue
  version=$(describe_version "$name")
  if [[ -z "$version" ]]; then
    PRUNABLE+=("$name")
  elif jq -e '.drainageInfo.drainageStatus == "drained"' <<<"$version" >/dev/null 2>&1; then
    PRUNABLE+=("$name")
    DRAINED+=("$name")
  fi
done < <(jq -r '.endpoints.value // {} | keys[]' <<<"$OUTPUTS")

if [[ ${#PRUNABLE[@]} -eq 0 ]]; then
  echo "Nothing to prune: every older endpoint still serves pinned workflows."
  exit 0
fi

echo "Pruning ${PRUNABLE[*]}"
scripts/infra.sh "$CURRENT_BUILD" "${PRUNABLE[@]}"

# The ${arr[@]+...} form keeps an empty array safe under set -u in bash 3.2.
for name in ${DRAINED[@]+"${DRAINED[@]}"}; do
  delete_version "$name" || true
done
