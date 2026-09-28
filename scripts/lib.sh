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
# not exist.
describe_version() {
  tcli worker deployment describe-version --deployment-name "$TEMPORAL_DEPLOYMENT_NAME" --build-id "$1" -o json \
    2>/dev/null || true
}

# delete_version BUILD_ID: deletes the version without waiting for it to drain.
delete_version() {
  if ! tcli worker deployment delete-version --deployment-name "$TEMPORAL_DEPLOYMENT_NAME" --build-id "$1" \
    --skip-drainage; then
    echo "pollers from the destroyed worker stay listed about 5 minutes; retry later" >&2
    return 1
  fi
}
