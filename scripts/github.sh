#!/usr/bin/env bash
# Syncs the GitHub App, then applies the github stack: demo repository,
# rulesets, Actions secrets (make github). The sync stores the app's current
# slug, which a rename in the app settings changes, and points the app's
# webhook at the aws stack's webhook_url, so a custom domain switched on or
# off never needs a manual edit in the app settings. It runs first, so that
# the install link and the stack's app_slug output use the current slug.
#
# The GitHub App must be registered first (make github-app). The rulesets
# are only created once the app is installed on the demo repository, so the
# stack is told whether it is, and the script ends with the install link
# while it is not.
set -euo pipefail

source scripts/lib.sh

: "${GITHUB_OWNER:?GITHUB_OWNER is not set}"

if ! aws secretsmanager get-secret-value --secret-id code-review-agentcore-temporal/github-app \
  --query ARN --output text >/dev/null 2>&1; then
  die "The GitHub App is not registered yet: run make github-app, then make up again."
fi

# A plain assignment, so that set -e stops here if the output is missing.
WEBHOOK_URL=$(tofu -chdir=infra/aws output -raw webhook_url)
uv run --quiet python -m agentcore_review_tools.github_app sync --url "$WEBHOOK_URL"

# installation-id prints the ID on stdout, or the install link on stderr:
# keep only the link, shown once the apply is done.
APP_INSTALLED=true
if ! INSTALL_NOTICE=$(uv run --quiet python -m agentcore_review_tools.github_app installation-id \
  --owner "$GITHUB_OWNER" --repo "$DEMO_REPO" 2>&1 >/dev/null); then
  APP_INSTALLED=false
fi

GITHUB_TOKEN=$(gh auth token)
export GITHUB_TOKEN
export TF_VAR_github_owner="$GITHUB_OWNER"
export TF_VAR_app_installed="$APP_INSTALLED"
tofu -chdir=infra/github apply -input=false -auto-approve

if [[ "$APP_INSTALLED" == true ]]; then
  echo "GitHub App is installed on $GITHUB_OWNER/$DEMO_REPO."
else
  echo "$INSTALL_NOTICE"
fi
