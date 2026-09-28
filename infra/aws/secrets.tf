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
