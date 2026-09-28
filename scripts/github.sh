#!/usr/bin/env bash
# Syncs the GitHub App (current slug, webhook URL), then applies the github
# stack: demo repository, rulesets, Actions secrets (make github). The
# rulesets need the app installed on the demo repository: until it is, they
# are left out and the script ends with the install link.
set -euo pipefail

source scripts/lib.sh

# A plain assignment, so that set -e stops here if the output is missing.
WEBHOOK_URL=$(tofu -chdir=infra/aws output -raw webhook_url)
uv run --quiet python -m agentcore_review_tools.github_app sync --url "$WEBHOOK_URL"

# installation-id exits with status 2 when the app is not installed, the
# install link on stderr. Any other failure stops here: taken for "not
# installed", it would make the apply destroy the rulesets.
if INSTALL_NOTICE=$(uv run --quiet python -m agentcore_review_tools.github_app installation-id \
  --owner "$GITHUB_OWNER" --repo "$DEMO_REPO" 2>&1 >/dev/null); then
  APP_INSTALLED=true
else
  status=$?
  [[ "$status" -eq 2 ]] || die "$INSTALL_NOTICE"
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
