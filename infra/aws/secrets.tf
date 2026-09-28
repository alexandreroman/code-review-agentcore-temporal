# Created empty: values come from make secrets, never from OpenTofu, so no
# secret value reaches the state.

resource "aws_secretsmanager_secret" "anthropic" {
  name                    = "${local.name}/anthropic-api-key"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret" "worker_cert" {
  name                    = "${local.name}/temporal-worker-cert"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret" "router_cert" {
  name                    = "${local.name}/temporal-router-cert"
  recovery_window_in_days = 0
}

# The worker reads the Anthropic key through AgentCore Identity, the same way on AgentCore and in the dev worker. The
# names are also in shared/src/agentcore_review_shared/secrets.py, which the dev worker reads.
resource "aws_bedrockagentcore_workload_identity" "worker" {
  name = "${local.name}-worker"
}

# EXTERNAL: the provider reads the secret above, so the key stays out of the state and make secrets still sets it.
# json_key is the field scripts/secrets.sh writes.
resource "aws_bedrockagentcore_api_key_credential_provider" "anthropic" {
  name                  = "${local.component_prefix}-anthropic"
  api_key_secret_source = "EXTERNAL"
  api_key_secret_config {
    secret_id = aws_secretsmanager_secret.anthropic.arn
    json_key  = "api_key"
  }
}

# Every account has one AgentCore Identity directory and token vault, both named default.
locals {
  agentcore_arn_prefix            = "arn:aws:bedrock-agentcore:${var.region}:${local.account_id}"
  workload_identity_directory_arn = "${local.agentcore_arn_prefix}:workload-identity-directory/default"
  token_vault_arn                 = "${local.agentcore_arn_prefix}:token-vault/default"
}
