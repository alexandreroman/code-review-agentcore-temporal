#!/usr/bin/env bash
# Pushes the Temporal mTLS client certificate from .env to Secrets Manager,
# where the worker and the router read it (make secrets).
#
# Every value is validated before anything is written. The secret is
# compared against its current value first, so re-running this is a no-op
# once Secrets Manager already holds the desired JSON.
set -euo pipefail

source scripts/lib.sh

require_pem() {
  local path="$1" var_name="$2"
  [[ -n "$path" ]] || die "make secrets: $var_name is not set"
  [[ -f "$path" ]] || die "make secrets: $path not found ($var_name)"
  grep -q -- "-----BEGIN " "$path" || die "make secrets: $path is not a PEM file ($var_name)"
}

require_pem "${TEMPORAL_TLS_CERT_PATH:-}" TEMPORAL_TLS_CERT_PATH
require_pem "${TEMPORAL_TLS_KEY_PATH:-}" TEMPORAL_TLS_KEY_PATH

SECRET_NAME=code-review-agentcore-temporal/temporal-cert
CERT_JSON=$(jq -n --rawfile cert "$TEMPORAL_TLS_CERT_PATH" --rawfile key "$TEMPORAL_TLS_KEY_PATH" \
  '{cert: $cert, key: $key}')

if ! current=$(aws secretsmanager get-secret-value --secret-id "$SECRET_NAME" \
  --query SecretString --output text 2>&1); then
  if [[ "$current" != *ResourceNotFoundException* ]]; then
    die "make secrets: $current (has make infra run?)"
  fi
  current=""
fi

if [[ -n "$current" ]] && [[ "$(jq -Sc . <<<"$current")" == "$(jq -Sc . <<<"$CERT_JSON")" ]]; then
  echo "$SECRET_NAME: unchanged"
  exit 0
fi

# A private temp file keeps the secret out of `ps`, which would show an
# inline --secret-string value; the EXIT trap removes it on every exit path,
# die included.
tmp=$(umask 077 && mktemp)
trap 'rm -f "$tmp"' EXIT
printf '%s' "$CERT_JSON" >"$tmp"
if ! error=$(aws secretsmanager put-secret-value --secret-id "$SECRET_NAME" \
  --secret-string "file://$tmp" 2>&1 1>/dev/null); then
  die "make secrets: $error (has make infra run?)"
fi
echo "$SECRET_NAME: updated"
