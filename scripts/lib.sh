# Shared helpers for the deployment scripts (sourced, not executed directly).
#
# Every apply of the aws stack goes through aws_apply: the endpoints a pinned
# workflow still needs live only in the stack outputs, so keeping them alive
# means re-reading those outputs before every apply and passing them back.

AWS_STACK="infra/aws"

die() {
  echo "$*" >&2
  exit 1
}

aws_outputs() {
  tofu -chdir="$AWS_STACK" output -json
}

# tcli ...: runs the temporal CLI with explicit mTLS flags. This build of the
# CLI ignores the TEMPORAL_TLS_CLIENT_CERT_PATH / TEMPORAL_TLS_CLIENT_KEY_PATH
# environment variables (the handshake fails silently), so every call goes
# through here instead of a bare `temporal`.
tcli() {
  temporal "$@" --tls-cert-path "$TEMPORAL_TLS_CERT_PATH" --tls-key-path "$TEMPORAL_TLS_KEY_PATH"
}

# aws_apply [BUILD_ID] [DROP...]: applies the aws stack with BUILD_ID as the
# deployed build (or the current one when omitted), keeping every endpoint
# except the one being applied and the DROP names.
aws_apply() {
  local build_id="${1:-}"
  if [[ $# -gt 0 ]]; then
    shift
  fi

  local outputs
  outputs=$(aws_outputs)
  if [[ -z "$build_id" ]]; then
    build_id=$(jq -r '.current_build.value // ""' <<<"$outputs")
  fi

  local drop_json="[]"
  if [[ $# -gt 0 ]]; then
    drop_json=$(printf '%s\n' "$@" | jq -R . | jq -sc .)
  fi
  if jq -e --arg build "$build_id" 'index($build) != null' <<<"$drop_json" >/dev/null; then
    die "refusing to drop the current build $build_id"
  fi

  local retained
  retained=$(jq -c --arg build "$build_id" --argjson drop "$drop_json" '
    (.endpoints.value // {})
    | to_entries
    | map(select(.key != $build and ((.key as $k | $drop | index($k)) == null)))
    | map({key, value: .value.version})
    | from_entries
  ' <<<"$outputs")

  TF_VAR_build_id="$build_id" TF_VAR_retained_endpoints="$retained" \
    tofu -chdir="$AWS_STACK" apply -input=false -auto-approve
}
