resource "aws_ecr_repository" "worker" {
  name                 = "${local.component_prefix}-worker"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = true
}

resource "aws_iam_role" "agentcore" {
  name = "${local.name}-agentcore"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "bedrock-agentcore.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = { StringEquals = { "aws:SourceAccount" = local.account_id } }
    }]
  })
}

resource "aws_iam_role_policy" "agentcore" {
  role = aws_iam_role.agentcore.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["ecr:GetAuthorizationToken"], Resource = "*" },
      {
        Effect   = "Allow"
        Action   = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"]
        Resource = aws_ecr_repository.worker.arn
      },
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
          "logs:DescribeLogStreams",
          "logs:DescribeLogGroups",
        ]
        Resource = "*"
      },
      { Effect = "Allow", Action = ["xray:PutTraceSegments", "xray:PutTelemetryRecords"], Resource = "*" },
      {
        Effect    = "Allow"
        Action    = ["cloudwatch:PutMetricData"]
        Resource  = "*"
        Condition = { StringEquals = { "cloudwatch:namespace" = "bedrock-agentcore" } }
      },
      {
        Effect = "Allow"
        Action = [
          "bedrock-agentcore:GetWorkloadAccessToken",
          "bedrock-agentcore:GetWorkloadAccessTokenForJWT",
          "bedrock-agentcore:GetWorkloadAccessTokenForUserId",
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = ["secretsmanager:GetSecretValue"]
        Resource = [
          aws_secretsmanager_secret.github_app.arn,
          aws_secretsmanager_secret.anthropic.arn,
          aws_secretsmanager_secret.worker_cert.arn,
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = "${aws_s3_bucket.snapshots.arn}/*"
      },
      { Effect = "Allow", Action = ["s3:ListBucket"], Resource = aws_s3_bucket.snapshots.arn },
    ]
  })
}

# Created by the first deploy: the runtime needs an image, which needs the ECR repository first.
resource "aws_bedrockagentcore_agent_runtime" "worker" {
  count              = local.deployed ? 1 : 0
  agent_runtime_name = local.runtime_name
  role_arn           = aws_iam_role.agentcore.arn

  agent_runtime_artifact {
    container_configuration {
      container_uri = "${aws_ecr_repository.worker.repository_url}:${var.build_id}"
    }
  }
  network_configuration {
    network_mode = "PUBLIC"
  }
  lifecycle_configuration {
    idle_runtime_session_timeout = var.idle_timeout
    max_lifetime                 = 3600
  }
  # Names and ARNs only: the worker reads secret values from Secrets Manager.
  environment_variables = {
    TEMPORAL_ADDRESS         = var.temporal_address
    TEMPORAL_NAMESPACE       = var.temporal_namespace
    TASK_QUEUE               = var.task_queue
    TEMPORAL_DEPLOYMENT_NAME = var.deployment_name
    TEMPORAL_BUILD_ID        = var.build_id
    TEMPORAL_CERT_SECRET_ARN = aws_secretsmanager_secret.worker_cert.arn
    ANTHROPIC_SECRET_ARN     = aws_secretsmanager_secret.anthropic.arn
    GITHUB_APP_SECRET_ARN    = aws_secretsmanager_secret.github_app.arn
    SNAPSHOTS_BUCKET         = aws_s3_bucket.snapshots.bucket
    ANTHROPIC_MODEL          = var.anthropic_model
    ANTHROPIC_EFFORT         = var.anthropic_effort
    MAX_PARALLEL_AGENTS      = tostring(var.max_parallel_agents)
  }

  depends_on = [aws_iam_role_policy.agentcore]
}

locals {
  # One endpoint per build: the new one follows the runtime version, earlier ones stay on theirs.
  endpoints = local.deployed ? merge(var.retained_endpoints, {
    (var.build_id) = aws_bedrockagentcore_agent_runtime.worker[0].agent_runtime_version
  }) : {}
}

resource "aws_bedrockagentcore_agent_runtime_endpoint" "build" {
  for_each              = local.endpoints
  name                  = each.key
  agent_runtime_id      = aws_bedrockagentcore_agent_runtime.worker[0].agent_runtime_id
  agent_runtime_version = each.value
  description           = "Worker build ${each.key}"
}
