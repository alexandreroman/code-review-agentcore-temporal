# Created empty: values come from make secrets, never from OpenTofu, so no
# secret value reaches the state.

# The GitHub App secret is created by make github-app, outside the stack, so
# that make destroy keeps the app's credentials and the next make up reuses
# the same app. Deployments that still track it forget it without deleting it.
removed {
  from = aws_secretsmanager_secret.github_app
  lifecycle {
    destroy = false
  }
}

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
