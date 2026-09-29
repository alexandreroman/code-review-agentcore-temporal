#!/usr/bin/env bash
# Sets up the GitHub side of the demo (make github):
#   1. registers the GitHub App on the first run (a browser page to confirm),
#      then syncs it (current slug, webhook URL);
#   2. applies the github stack: demo repository, Actions secrets, and the
#      rulesets once the app is installed on the demo repository;
#   3. pushes the demo application from demo/ into the demo repository
#      while it is empty, then runs its reset workflow once.
# When the app is not installed yet, the script opens its install link and
# waits for the installation before it adds the rulesets.
set -euo pipefail

source scripts/lib.sh
source scripts/demo-repo.sh

github_app() {
  uv run --quiet python -m agentcore_review_tools.github_app "$@"
}

# apply_github_stack APP_INSTALLED: the rulesets name the app as a bypass
# actor, which GitHub accepts only once the app is installed.
apply_github_stack() {
  TF_VAR_app_installed="$1" tofu -chdir=infra/github apply -input=false -auto-approve
}

# A plain assignment, so that set -e stops here if the output is missing.
WEBHOOK_URL=$(tofu -chdir=infra/aws output -raw webhook_url)
github_app register --owner "$GITHUB_OWNER" --name "$GITHUB_APP_NAME" --port "$GITHUB_APP_CALLBACK_PORT" \
  --webhook-url "$WEBHOOK_URL"
github_app sync --url "$WEBHOOK_URL"

# installation-id exits with status 2 when the app is not installed, the
# install link on stderr. Any other failure stops here: taken for "not
# installed", it would make the apply destroy the rulesets.
if INSTALL_NOTICE=$(github_app installation-id --owner "$GITHUB_OWNER" --repo "$DEMO_REPO" 2>&1 >/dev/null); then
  APP_INSTALLED=true
else
  status=$?
  [[ "$status" -eq 2 ]] || die "$INSTALL_NOTICE"
  APP_INSTALLED=false
fi

GITHUB_TOKEN=$(gh auth token)
export GITHUB_TOKEN
export TF_VAR_github_owner="$GITHUB_OWNER"

if [[ "$APP_INSTALLED" == false ]]; then
  # The app can only be installed on a repository that exists.
  apply_github_stack false
fi
fill_demo_repo
if [[ "$APP_INSTALLED" == false ]]; then
  # Opens the install link and waits; any failure (timeout included) stops
  # here, with its message on stderr.
  github_app installation-id --wait --owner "$GITHUB_OWNER" --repo "$DEMO_REPO" >/dev/null
fi
apply_github_stack true

# Only right after the first copy: a routine make up leaves the demo as it is.
if [[ "$DEMO_REPO_FILLED" == true ]]; then
  reset_demo_repo
fi
echo "GitHub App is installed on $GITHUB_OWNER/$DEMO_REPO."
