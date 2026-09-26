#!/usr/bin/env bash
# Pushes the Anthropic key and the Temporal mTLS certificates from .env to
# Secrets Manager (make secrets).
#
# Every value is validated before anything is written. Each secret is
# compared against its current value first, so re-running this is a no-op
# once Secrets Manager already holds the desired JSON.
set -euo pipefail

source scripts/lib.sh

PREFIX="temporal-agentic-review"

require_pem() {
  local path="$1" var_name="$2"
  [[ -n "$path" ]] || die "make secrets: $var_name is not set"
  [[ -f "$path" ]] || die "make secrets: $path not found ($var_name)"
  grep -q -- "-----BEGIN " "$path" || die "make secrets: $path is not a PEM file ($var_name)"
}

# sync_secret NAME JSON: writes JSON to the secret NAME unless it is already
# there, and prints "<name>: updated" or "<name>: unchanged".
sync_secret() {
  local name="$1" json="$2" current

  if ! current=$(aws secretsmanager get-secret-value --secret-id "$name" \
    --query SecretString --output text 2>&1); then
    if [[ "$current" != *ResourceNotFoundException* ]]; then
      die "make secrets: $current (has make infra run?)"
    fi
    current=""
  fi

  if [[ -n "$current" ]] && [[ "$(jq -Sc . <<<"$current")" == "$(jq -Sc . <<<"$json")" ]]; then
    echo "$name: unchanged"
    return
  fi

  local tmp
  tmp=$(umask 077 && mktemp)
  trap 'rm -f "$tmp"' RETURN
  printf '%s' "$json" >"$tmp"
  local error
  if ! error=$(aws secretsmanager put-secret-value --secret-id "$name" --secret-string "file://$tmp" 2>&1 1>/dev/null); then
    die "make secrets: $error (has make infra run?)"
  fi
  echo "$name: updated"
}

[[ -n "${ANTHROPIC_API_KEY:-}" ]] || die "make secrets: ANTHROPIC_API_KEY is empty in .env"
require_pem "${TEMPORAL_WORKER_CERT_PATH:-}" TEMPORAL_WORKER_CERT_PATH
require_pem "${TEMPORAL_WORKER_KEY_PATH:-}" TEMPORAL_WORKER_KEY_PATH
require_pem "${TEMPORAL_ROUTER_CERT_PATH:-}" TEMPORAL_ROUTER_CERT_PATH
require_pem "${TEMPORAL_ROUTER_KEY_PATH:-}" TEMPORAL_ROUTER_KEY_PATH

sync_secret "$PREFIX/anthropic-api-key" "$(jq -n '{api_key: env.ANTHROPIC_API_KEY}')"
sync_secret "$PREFIX/temporal-worker-cert" "$(jq -n --rawfile cert "$TEMPORAL_WORKER_CERT_PATH" \
  --rawfile key "$TEMPORAL_WORKER_KEY_PATH" '{cert: $cert, key: $key}')"
sync_secret "$PREFIX/temporal-router-cert" "$(jq -n --rawfile cert "$TEMPORAL_ROUTER_CERT_PATH" \
  --rawfile key "$TEMPORAL_ROUTER_KEY_PATH" '{cert: $cert, key: $key}')"
