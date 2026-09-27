#!/usr/bin/env bash
# Applies the github stack: demo repository, rulesets, Actions secrets
# (make github).
#
# The GitHub App must be registered first (make github-app). The rulesets
# are only created once the app is installed on the demo repository, so the
# stack is told whether it is.
set -euo pipefail

source scripts/lib.sh

: "${GITHUB_OWNER:?GITHUB_OWNER is not set}"

if ! aws secretsmanager get-secret-value --secret-id temporal-agentcore-review-demo/github-app \
  --query ARN --output text >/dev/null 2>&1; then
  die "The GitHub App is not registered yet: run make github-app, then make up again."
fi

APP_INSTALLED=false
if uv run --quiet python -m agentcore_review_tools.github_app installation-id \
  --owner "$GITHUB_OWNER" --repo "$DEMO_REPO" >/dev/null 2>&1; then
  APP_INSTALLED=true
fi

GITHUB_TOKEN=$(gh auth token)
export GITHUB_TOKEN
export TF_VAR_github_owner="$GITHUB_OWNER"
export TF_VAR_app_installed="$APP_INSTALLED"
tofu -chdir=infra/github apply -input=false -auto-approve
