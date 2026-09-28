# The Temporal mTLS client certificate, read by the worker and the router.
# Created empty: the value comes from make secrets, never from OpenTofu, so no
# secret value reaches the state.
resource "aws_secretsmanager_secret" "temporal_cert" {
  name                    = "${local.name}/temporal-cert"
  recovery_window_in_days = 0
}
