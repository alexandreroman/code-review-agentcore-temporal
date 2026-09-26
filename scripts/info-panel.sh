#!/usr/bin/env bash
# Publishes endpoints and links to the Casper workspace info panel
# (make info-publish, and make dev with --local-worker).
#
# Everything comes from the stack outputs and the environment; nothing is
# recomputed here. Outside a Casper workspace, or on any error, this does
# nothing: the panel must never make a target fail.
set -euo pipefail

source scripts/lib.sh

LOCAL_WORKER=false
[[ "${1:-}" != "--local-worker" ]] || LOCAL_WORKER=true

[[ -n "${CASPER_WORKSPACE_ID:-}" ]] || exit 0
command -v casper >/dev/null 2>&1 || exit 0

# stack_outputs STACK: that stack's `tofu output -json`, or "{}" if the
# stack was never applied (or any other error).
stack_outputs() {
  tofu -chdir="$1" output -json 2>/dev/null || echo '{}'
}

# value JSON KEY: that output's value, or an empty string.
value() {
  jq -r --arg key "$2" '.[$key].value // empty' <<<"$1"
}

# log_group_url REGION NAME: the CloudWatch console link for that log group,
# with the console's double URL-encoding ($25 in front of every %-escape).
log_group_url() {
  local region="$1" name="$2" encoded
  encoded=$(jq -rn --arg name "$name" '$name | @uri' | sed 's/%/$25/g')
  echo "https://${region}.console.aws.amazon.com/cloudwatch/home?region=${region}#logsV2:log-groups/log-group/${encoded}"
}

AWS_JSON=$(stack_outputs infra/aws)
GITHUB_JSON=$(stack_outputs infra/github)

render() {
  local router_url build runtime_id slug router_log_group

  router_url=$(value "$AWS_JSON" router_url)
  build=$(value "$AWS_JSON" current_build)
  runtime_id=$(value "$AWS_JSON" runtime_id)
  slug=$(value "$GITHUB_JSON" app_slug)

  echo "# Agentic Code Review with AgentCore x Temporal"
  echo
  echo "## Webhook"
  echo
  if [[ -n "$router_url" ]]; then
    echo "\`$router_url\`"
  else
    echo "Not deployed yet: run \`make up\`."
  fi

  echo
  echo "## Links"
  echo
  echo "- [Temporal workflows](https://cloud.temporal.io/namespaces/${TEMPORAL_NAMESPACE}/workflows)"
  echo "- [Worker Deployments](https://cloud.temporal.io/namespaces/${TEMPORAL_NAMESPACE}/worker-deployments)"
  if [[ -n "${GITHUB_OWNER:-}" && -n "${DEMO_REPO:-}" ]]; then
    local base="https://github.com/${GITHUB_OWNER}/${DEMO_REPO}"
    echo "- [Demo repository](${base}) · [pull requests](${base}/pulls)"
    echo "- [Reset demo workflow](${base}/actions/workflows/reset-demo.yml)"
  fi
  if [[ -n "$slug" ]]; then
    echo "- [GitHub App](https://github.com/apps/${slug})"
  fi
  echo "- [AgentCore console](https://${AWS_REGION}.console.aws.amazon.com/bedrock-agentcore/home?region=${AWS_REGION})"
  router_log_group=$(value "$AWS_JSON" router_log_group)
  if [[ -n "$router_log_group" ]]; then
    echo "- [Router logs]($(log_group_url "$AWS_REGION" "$router_log_group"))"
  fi
  if [[ -n "$runtime_id" && -n "$build" ]]; then
    echo "- [Worker logs]($(log_group_url "$AWS_REGION" "/aws/bedrock-agentcore/runtimes/${runtime_id}-${build}"))"
  fi

  echo
  echo "## Worker"
  echo
  if [[ -n "$build" ]]; then
    echo "- Current version: \`${TEMPORAL_DEPLOYMENT_NAME}:${build}\`"
    echo "- Endpoint: \`$(value "$AWS_JSON" current_endpoint_arn)\`"
  else
    echo "- No version deployed: run \`make up\`."
  fi
  if [[ "$LOCAL_WORKER" == true ]]; then
    echo "- Local worker: running on \`${DEV_TASK_QUEUE}\`"
  else
    echo "- Local worker: stopped (\`make dev\` starts it)"
  fi
}

DOCUMENT=$(mktemp)
mv "$DOCUMENT" "${DOCUMENT}.md"
DOCUMENT="${DOCUMENT}.md"
trap 'rm -f "$DOCUMENT"' EXIT

render >"$DOCUMENT"
casper info set --file "$DOCUMENT" >/dev/null 2>&1 || true
