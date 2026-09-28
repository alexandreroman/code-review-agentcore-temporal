#!/usr/bin/env bash
# Destroys the AWS resources (make destroy), then cleans up the Temporal
# Worker Deployment and the AgentCore log groups it leaves behind.
#
# The GitHub side, the GitHub App secret (created outside the stack), the
# state bucket and its KMS key stay: only the aws stack and the Worker
# Deployment are torn down. Everything after the `tofu destroy` is best
# effort: the AWS side is already gone by then, so a failure here only
# prints a warning instead of aborting.
set -euo pipefail

source scripts/lib.sh

require_cloudflare

BUILDS=$(jq -r '.endpoints.value // {} | keys[]' <<<"$(aws_outputs)")

scripts/kill-sessions.sh || true

# `tofu destroy` ignores the removed block of secrets.tf: a stack last applied
# while it still managed the GitHub App secret would delete it. Forget the
# secret first, as the next apply would.
if tofu -chdir=infra/aws state list aws_secretsmanager_secret.github_app >/dev/null 2>&1; then
  tofu -chdir=infra/aws state rm aws_secretsmanager_secret.github_app >/dev/null
fi

echo "Destroying the AWS resources. The GitHub App credentials stay in Secrets Manager: the next make up reuses the" \
  "same app (and, with a custom domain, the same webhook URL). The demo repository and the state bucket stay."

# Interactive: tofu asks for confirmation. A refusal exits non-zero here,
# and set -e stops the script before the Temporal cleanup below.
tofu -chdir=infra/aws destroy -input=false

warn_on_failure() {
  "$@" || echo "warning: $*" >&2
}

warn_on_failure tcli worker deployment set-current-version --deployment-name "$TEMPORAL_DEPLOYMENT_NAME" \
  --unversioned --yes

while IFS= read -r build; do
  [[ -n "$build" ]] || continue
  delete_version "$build" || true
done <<<"$BUILDS"

warn_on_failure tcli worker deployment delete --name "$TEMPORAL_DEPLOYMENT_NAME"

# The prefix covers the log groups of every runtime of earlier destroy/up
# cycles, and needs no stack output, so a re-run after a partial destroy works.
LOG_GROUPS=$(aws logs describe-log-groups \
  --log-group-name-prefix "/aws/bedrock-agentcore/runtimes/agentcore_review_demo_worker" \
  --query 'logGroups[].logGroupName' --output text) || {
  echo "warning: cannot list the AgentCore log groups" >&2
  LOG_GROUPS=""
}
for group in $LOG_GROUPS; do
  warn_on_failure aws logs delete-log-group --log-group-name "$group"
done
