# Role that Temporal Cloud's Worker Controller assumes to invoke the runtime.
# The principals are Temporal's own AWS accounts, as documented by Temporal
# for Serverless Workers on AgentCore.

resource "random_password" "external_id" {
  length  = 32
  special = false
}

resource "aws_iam_role" "temporal_invoke" {
  name = "${local.name}-temporal-invoke"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = { AWS = [
        "arn:aws:iam::902542641901:role/wci-lambda-invoke",
        "arn:aws:iam::160190466495:role/wci-lambda-invoke",
        "arn:aws:iam::819232936619:role/wci-lambda-invoke",
        "arn:aws:iam::829909441867:role/wci-lambda-invoke",
        "arn:aws:iam::354116250941:role/wci-lambda-invoke",
      ] }
      Action    = "sts:AssumeRole"
      Condition = { StringEquals = { "sts:ExternalId" = random_password.external_id.result } }
    }]
  })
}

resource "aws_iam_role_policy" "temporal_invoke" {
  role = aws_iam_role.temporal_invoke.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["bedrock-agentcore:InvokeAgentRuntime", "bedrock-agentcore:GetAgentRuntimeEndpoint"]
      Resource = [local.runtime_arn_pattern]
    }]
  })
}
