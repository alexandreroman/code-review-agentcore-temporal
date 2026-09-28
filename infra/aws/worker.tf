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
      {
        Effect = "Allow"
        Action = ["secretsmanager:GetSecretValue"]
        # The Anthropic secret stays: AgentCore Identity reads it with the caller's permissions (EXTERNAL provider).
        Resource = [
          local.github_app_secret_arn_pattern,
          aws_secretsmanager_secret.anthropic.arn,
          aws_secretsmanager_secret.worker_cert.arn,
        ]
      },
      {
        Effect = "Allow"
        Action = ["bedrock-agentcore:GetWorkloadAccessToken"]
        Resource = [
          local.workload_identity_directory_arn,
          aws_bedrockagentcore_workload_identity.worker.workload_identity_arn,
        ]
      },
      {
        Effect = "Allow"
        Action = ["bedrock-agentcore:GetResourceApiKey"]
        Resource = [
          local.workload_identity_directory_arn,
          aws_bedrockagentcore_workload_identity.worker.workload_identity_arn,
          local.token_vault_arn,
          aws_bedrockagentcore_api_key_credential_provider.anthropic.credential_provider_arn,
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = "${aws_s3_bucket.snapshots.arn}/*"
      },
      { Effect = "Allow", Action = ["s3:ListBucket"], Resource = aws_s3_bucket.snapshots.arn },
      # Spans (TRACING=on), sent to the X-Ray OTLP endpoint: the write actions of the AWSXrayWriteOnlyAccess policy.
      { Effect = "Allow", Action = ["xray:PutTraceSegments", "xray:PutTelemetryRecords"], Resource = "*" },
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
  # Names and ARNs only: the worker reads secret values from Secrets Manager and AgentCore Identity.
  environment_variables = {
    TEMPORAL_ADDRESS              = var.temporal_address
    TEMPORAL_NAMESPACE            = var.temporal_namespace
    TASK_QUEUE                    = var.task_queue
    TEMPORAL_DEPLOYMENT_NAME      = var.deployment_name
    TEMPORAL_BUILD_ID             = var.build_id
    TEMPORAL_CERT_SECRET_ARN      = aws_secretsmanager_secret.worker_cert.arn
    GITHUB_APP_SECRET_ID          = local.github_app_secret_name
    WORKLOAD_IDENTITY_NAME        = aws_bedrockagentcore_workload_identity.worker.name
    ANTHROPIC_CREDENTIAL_PROVIDER = aws_bedrockagentcore_api_key_credential_provider.anthropic.name
    SNAPSHOTS_BUCKET              = aws_s3_bucket.snapshots.bucket
    ANTHROPIC_MODEL               = var.anthropic_model
    ANTHROPIC_EFFORT              = var.anthropic_effort
    MAX_PARALLEL_AGENTS           = tostring(var.max_parallel_agents)
    TRACING                       = var.tracing
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
