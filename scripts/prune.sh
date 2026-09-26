#!/usr/bin/env bash
# Removes the endpoints (and Temporal versions) of builds no pinned
# workflow still uses (make prune).
#
# An endpoint is prunable when its Worker Deployment Version is gone
# (describe fails) or fully drained. The current build is never touched.
set -euo pipefail

source scripts/lib.sh

OUTPUTS=$(aws_outputs)
CURRENT_BUILD=$(jq -r '.current_build.value // ""' <<<"$OUTPUTS")

# describe_version BUILD_ID: prints the version's JSON, or nothing if it
# does not exist any more.
describe_version() {
  tcli worker deployment describe-version --deployment-name "$TEMPORAL_DEPLOYMENT_NAME" --build-id "$1" -o json \
    2>/dev/null || true
}

PRUNABLE=()
VERSION_EXISTS=()
while IFS= read -r name; do
  [[ -n "$name" && "$name" != "$CURRENT_BUILD" ]] || continue
  version=$(describe_version "$name")
  if [[ -z "$version" ]]; then
    PRUNABLE+=("$name")
    VERSION_EXISTS+=(false)
  elif jq -e '.drainageInfo.drainageStatus == "drained"' <<<"$version" >/dev/null 2>&1; then
    PRUNABLE+=("$name")
    VERSION_EXISTS+=(true)
  fi
done < <(jq -r '.endpoints.value // {} | keys[]' <<<"$OUTPUTS")

if [[ ${#PRUNABLE[@]} -eq 0 ]]; then
  echo "Nothing to prune: every older endpoint still serves pinned workflows."
  exit 0
fi

echo "Pruning ${PRUNABLE[*]}"
aws_apply "" "${PRUNABLE[@]}"

for i in "${!PRUNABLE[@]}"; do
  [[ "${VERSION_EXISTS[$i]}" == true ]] || continue
  name="${PRUNABLE[$i]}"
  if ! tcli worker deployment delete-version --deployment-name "$TEMPORAL_DEPLOYMENT_NAME" --build-id "$name" \
    --skip-drainage; then
    echo "warning: version $name cannot be deleted yet (pollers stay listed ~5 min): re-run make prune later" >&2
  fi
done
