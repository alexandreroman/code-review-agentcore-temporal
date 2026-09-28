#!/usr/bin/env bash
# Drives a pull request's workflow by hand, the way the router does from
# webhooks (make review-pr):
#   update  signal-with-start pr_updated with the pull request's current head
#   fix     signal fix_requested, as a /fix comment does
#   close   signal pr_closed with the pull request's state on GitHub
set -euo pipefail

source scripts/lib.sh

[[ $# -eq 5 ]] || die "usage: scripts/review-pr.sh OWNER REPO NUMBER update|fix|close QUEUE"
owner="$1" repo="$2" number="$3" action="$4" queue="$5"
workflow_id=$(printf 'pr-%s-%s-%s' "$owner" "$repo" "$number" | tr '[:upper:]' '[:lower:]')
delivery="manual-$(date +%s)"

case "$action" in
  update)
    head=$(gh pr view "$number" --repo "$owner/$repo" --json headRefOid --jq .headRefOid)
    installation=$(uv run --quiet python -m agentcore_review_tools.github_app installation-id \
      --owner "$owner" --repo "$repo")
    input=$(jq -nc --arg owner "$owner" --arg repo "$repo" --argjson number "$number" \
      --argjson installation "$installation" \
      --argjson warning "$PR_IDLE_WARNING_SECONDS" --argjson close "$PR_IDLE_CLOSE_SECONDS" \
      '{pr: {owner: $owner, repo: $repo, number: $number, installation_id: $installation},
        idle_warning_seconds: $warning, idle_close_seconds: $close}')
    signal=$(jq -nc --arg sha "$head" --arg delivery "$delivery" '{head_sha: $sha, delivery_id: $delivery}')
    tcli workflow signal-with-start --type PullRequestWorkflow --task-queue "$queue" --workflow-id "$workflow_id" \
      --input "$input" --signal-name pr_updated --signal-input "$signal" \
      --id-conflict-policy UseExisting --id-reuse-policy AllowDuplicate
    ;;
  fix)
    signal=$(jq -nc --arg by "$(gh api user --jq .login)" --arg delivery "$delivery" \
      '{requested_by: $by, delivery_id: $delivery}')
    tcli workflow signal --workflow-id "$workflow_id" --name fix_requested --input "$signal"
    ;;
  close)
    signal=$(gh pr view "$number" --repo "$owner/$repo" --json state,mergedBy |
      jq -c --arg delivery "$delivery" \
        '{merged: (.state == "MERGED"), closed_by: .mergedBy.login, delivery_id: $delivery}')
    tcli workflow signal --workflow-id "$workflow_id" --name pr_closed --input "$signal"
    ;;
  *)
    die "make review-pr: ACTION must be update, fix or close, not $action"
    ;;
esac
echo "Workflow $workflow_id on $queue: https://cloud.temporal.io/namespaces/$TEMPORAL_NAMESPACE/workflows/$workflow_id"
