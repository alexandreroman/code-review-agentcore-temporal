#!/usr/bin/env bash
# Creates the OpenTofu state bucket and its KMS key (make bootstrap), once per
# AWS account. The bucket name ends with the account ID, so it is unique;
# when that bucket already exists, this does nothing.
set -euo pipefail

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
BUCKET="code-review-agentcore-temporal-tfstate-$ACCOUNT_ID"

if aws s3api head-bucket --bucket "$BUCKET" >/dev/null 2>&1; then
  echo "State bucket $BUCKET already exists"
  exit 0
fi

tofu -chdir=infra/bootstrap init -input=false
tofu -chdir=infra/bootstrap apply -input=false -auto-approve
