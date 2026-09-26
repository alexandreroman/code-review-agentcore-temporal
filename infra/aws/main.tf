data "aws_caller_identity" "current" {}

locals {
  name             = "temporal-agentcore-review-demo"
  component_prefix = "agentcore-review-demo"
  account_id       = data.aws_caller_identity.current.account_id
  deployed         = var.build_id != ""
  runtime_name     = "agentcore_review_demo_worker"
  # Runtime IDs are "<runtime name>-<10 characters>"; a pattern avoids depending on the runtime existing.
  runtime_arn_pattern = "arn:aws:bedrock-agentcore:${var.region}:${local.account_id}:runtime/${local.runtime_name}-*"
}
