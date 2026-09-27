data "aws_caller_identity" "current" {}

locals {
  name             = "code-review-agentcore-temporal"
  component_prefix = "agentcore-review-demo"
  account_id       = data.aws_caller_identity.current.account_id
  deployed         = var.build_id != ""
  runtime_name     = "agentcore_review_demo_worker"
  router_name      = "${local.component_prefix}-router"
  # Runtime IDs are "<runtime name>-<10 characters>"; a pattern avoids depending on the runtime existing.
  runtime_arn_pattern = "arn:aws:bedrock-agentcore:${var.region}:${local.account_id}:runtime/${local.runtime_name}-*"
  # Created by make github-app, outside the stack (see secrets.tf). Secrets Manager appends 6 random characters to
  # the ARN; a pattern avoids depending on the secret existing, and GetSecretValue accepts the name.
  github_app_secret_name = "${local.name}/github-app"
  github_app_secret_arn_pattern = (
    "arn:aws:secretsmanager:${var.region}:${local.account_id}:secret:${local.github_app_secret_name}-*"
  )
}
