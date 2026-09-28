# shellcheck shell=bash
# Shared helpers for the deployment scripts (sourced, not executed directly).

die() {
  echo "$*" >&2
  exit 1
}

aws_outputs() {
  tofu -chdir=infra/aws output -json
}

# require_cloudflare: stops when a custom domain is set without the Cloudflare
# settings its DNS records need (every plan of the aws stack, destroy included).
require_cloudflare() {
  [[ -n "${DOMAIN_NAME:-}" ]] || return 0
  if [[ -z "${CLOUDFLARE_API_TOKEN:-}" || -z "${CLOUDFLARE_ZONE_ID:-}" ]]; then
    die "DOMAIN_NAME is set: the custom domain also needs CLOUDFLARE_API_TOKEN and CLOUDFLARE_ZONE_ID in .env."
  fi
}

# tcli ...: runs the temporal CLI with explicit mTLS flags. This build of the
# CLI ignores the TEMPORAL_TLS_CLIENT_CERT_PATH / TEMPORAL_TLS_CLIENT_KEY_PATH
# environment variables (the handshake fails silently), so every call goes
# through here instead of a bare `temporal`.
tcli() {
  temporal "$@" --tls-cert-path "$TEMPORAL_TLS_CERT_PATH" --tls-key-path "$TEMPORAL_TLS_KEY_PATH"
}

# describe_version BUILD_ID: prints the version's JSON, or nothing if it does
# not exist. Any other error (TLS, timeout) fails, so that a caller assigning
# the result (version=$(describe_version ...)) stops under set -e.
describe_version() {
  local output
  if output=$(tcli worker deployment describe-version --deployment-name "$TEMPORAL_DEPLOYMENT_NAME" \
    --build-id "$1" -o json 2>&1); then
    echo "$output"
  elif [[ "$output" != *"Worker Deployment Version not found"* ]]; then
    die "$output"
  fi
}

# delete_version BUILD_ID: deletes the version without waiting for it to drain.
delete_version() {
  if ! tcli worker deployment delete-version --deployment-name "$TEMPORAL_DEPLOYMENT_NAME" --build-id "$1" \
    --skip-drainage; then
    echo "a version with recent pollers cannot be deleted for about 5 minutes; retry later" >&2
    return 1
  fi
}
