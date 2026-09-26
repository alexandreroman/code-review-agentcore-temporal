output "router_url" {
  value = aws_lambda_function_url.router.function_url
}

output "router_log_group" {
  value = aws_cloudwatch_log_group.router.name
}

output "ecr_repository_url" {
  value = aws_ecr_repository.worker.repository_url
}

output "snapshots_bucket" {
  value = aws_s3_bucket.snapshots.bucket
}

output "runtime_arn" {
  value = local.deployed ? aws_bedrockagentcore_agent_runtime.worker[0].agent_runtime_arn : ""
}

output "runtime_id" {
  value = local.deployed ? aws_bedrockagentcore_agent_runtime.worker[0].agent_runtime_id : ""
}

output "current_build" {
  value = var.build_id
}

output "current_endpoint_arn" {
  value = local.deployed ? (
    aws_bedrockagentcore_agent_runtime_endpoint.build[var.build_id].agent_runtime_endpoint_arn
  ) : ""
}

output "endpoints" {
  value = {
    for name, endpoint in aws_bedrockagentcore_agent_runtime_endpoint.build :
    name => { arn = endpoint.agent_runtime_endpoint_arn, version = endpoint.agent_runtime_version }
  }
}

output "temporal_invoke_role_arn" {
  value = aws_iam_role.temporal_invoke.arn
}

output "temporal_external_id" {
  value     = random_password.external_id.result
  sensitive = true
}

output "secret_arns" {
  value = {
    github_app  = aws_secretsmanager_secret.github_app.arn
    anthropic   = aws_secretsmanager_secret.anthropic.arn
    worker_cert = aws_secretsmanager_secret.worker_cert.arn
    router_cert = aws_secretsmanager_secret.router_cert.arn
  }
}
