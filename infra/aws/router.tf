data "archive_file" "router" {
  type        = "zip"
  source_dir  = "${path.module}/../../build/router"
  output_path = "${path.module}/../../build/router.zip"
}

data "archive_file" "router_deps" {
  type        = "zip"
  source_dir  = "${path.module}/../../build/router-deps"
  output_path = "${path.module}/../../build/router-deps.zip"
}

# Third-party dependencies change only with uv.lock: as a layer they are uploaded once,
# and a router code change uploads only the small function zip.
resource "aws_lambda_layer_version" "router_deps" {
  layer_name               = "${local.router_name}-deps"
  filename                 = data.archive_file.router_deps.output_path
  source_code_hash         = data.archive_file.router_deps.output_base64sha256
  compatible_runtimes      = ["python3.14"]
  compatible_architectures = ["arm64"]
}

resource "aws_cloudwatch_log_group" "router" {
  name              = "/aws/lambda/${local.router_name}"
  retention_in_days = 7
}

resource "aws_iam_role" "router" {
  name = local.router_name
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "lambda.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}

resource "aws_iam_role_policy" "router" {
  role = aws_iam_role.router.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.router.arn}:*"
      },
      {
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = [local.github_app_secret_arn_pattern, aws_secretsmanager_secret.router_cert.arn]
      },
      { Effect = "Allow", Action = ["bedrock-agentcore:StopRuntimeSession"], Resource = [local.runtime_arn_pattern] },
      # Asynchronous self-invocation that finishes a /kill.
      {
        Effect   = "Allow"
        Action   = ["lambda:InvokeFunction"]
        Resource = "arn:aws:lambda:${var.region}:${local.account_id}:function:${local.router_name}"
      },
      # Active tracing (TRACING=on): Lambda sends the invocation's segments with the function's role.
      { Effect = "Allow", Action = ["xray:PutTraceSegments", "xray:PutTelemetryRecords"], Resource = "*" },
    ]
  })
}

resource "aws_lambda_function" "router" {
  function_name    = local.router_name
  role             = aws_iam_role.router.arn
  runtime          = "python3.14"
  architectures    = ["arm64"]
  handler          = "agentcore_review_router.handler.handler"
  filename         = data.archive_file.router.output_path
  source_code_hash = data.archive_file.router.output_base64sha256
  layers           = [aws_lambda_layer_version.router_deps.arn]
  memory_size      = 512
  timeout          = 10

  logging_config {
    log_format = "JSON"
    log_group  = aws_cloudwatch_log_group.router.name
  }

  # PassThrough is Lambda's default: no segment of its own, the invocations are not traced.
  tracing_config {
    mode = var.tracing == "on" ? "Active" : "PassThrough"
  }

  environment {
    variables = {
      GITHUB_APP_SECRET_ID     = local.github_app_secret_name
      TEMPORAL_CERT_SECRET_ARN = aws_secretsmanager_secret.router_cert.arn
      TEMPORAL_ADDRESS         = var.temporal_address
      TEMPORAL_NAMESPACE       = var.temporal_namespace
      TASK_QUEUE               = var.task_queue
      DEV_TASK_QUEUE           = var.dev_task_queue
      DEV_BRANCH_PREFIX        = var.dev_branch_prefix
      PR_IDLE_WARNING_SECONDS  = tostring(var.pr_idle_warning_seconds)
      PR_IDLE_CLOSE_SECONDS    = tostring(var.pr_idle_close_seconds)
      AGENTCORE_RUNTIME_ARN    = local.deployed ? aws_bedrockagentcore_agent_runtime.worker[0].agent_runtime_arn : ""
      TRACING                  = var.tracing
    }
  }

  depends_on = [aws_iam_role_policy.router]
}

resource "aws_lambda_function_url" "router" {
  function_name      = aws_lambda_function.router.function_name
  authorization_type = "NONE"
}

# A public Function URL needs both permissions.
resource "aws_lambda_permission" "url" {
  statement_id           = "FunctionUrlPublic"
  action                 = "lambda:InvokeFunctionUrl"
  function_name          = aws_lambda_function.router.function_name
  principal              = "*"
  function_url_auth_type = "NONE"
}

resource "aws_lambda_permission" "invoke" {
  statement_id             = "FunctionUrlInvoke"
  action                   = "lambda:InvokeFunction"
  function_name            = aws_lambda_function.router.function_name
  principal                = "*"
  invoked_via_function_url = true
}

# The asynchronous self-invocation that finishes a /kill posts a comment: a retry would post it twice.
resource "aws_lambda_function_event_invoke_config" "router" {
  function_name                = aws_lambda_function.router.function_name
  maximum_retry_attempts       = 0
  maximum_event_age_in_seconds = 60
}
