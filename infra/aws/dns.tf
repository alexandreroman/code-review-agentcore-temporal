# Optional custom domain for the webhook: ACM certificate, API Gateway HTTP
# API and Cloudflare DNS records.
#
# Gated on var.domain_name: leave it empty and none of this is created, the
# webhook stays on the Function URL. The custom domain needs API Gateway in
# front of the router because a Function URL only answers to its own hostname
# (SNI and Host header) and cannot have a custom domain, and rewriting the
# Host header in Cloudflare is an Enterprise-only feature.
#
# Cloudflare proxy stays OFF (DNS only): API Gateway terminates TLS with the
# ACM certificate.

locals {
  use_custom_domain = var.domain_name != ""
  webhook_fqdn      = "${var.subdomain}.${var.domain_name}"
}

resource "aws_acm_certificate" "webhook" {
  count = local.use_custom_domain ? 1 : 0

  domain_name       = local.webhook_fqdn
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }
}

resource "cloudflare_dns_record" "cert_validation" {
  for_each = local.use_custom_domain ? {
    for dvo in aws_acm_certificate.webhook[0].domain_validation_options : dvo.domain_name => dvo
  } : {}

  zone_id = var.cloudflare_zone_id

  # Cloudflare v5 expects the FQDN without a trailing dot.
  name    = trimsuffix(each.value.resource_record_name, ".")
  type    = each.value.resource_record_type
  content = trimsuffix(each.value.resource_record_value, ".")
  ttl     = 60
  proxied = false
}

resource "aws_acm_certificate_validation" "webhook" {
  count = local.use_custom_domain ? 1 : 0

  certificate_arn         = aws_acm_certificate.webhook[0].arn
  validation_record_fqdns = [for record in cloudflare_dns_record.cert_validation : record.name]
}

# Quick create: target adds the default route, a Lambda proxy integration (payload format 2.0) and an
# auto-deployed $default stage.
resource "aws_apigatewayv2_api" "webhook" {
  count = local.use_custom_domain ? 1 : 0

  name          = local.router_name
  protocol_type = "HTTP"
  target        = aws_lambda_function.router.arn
  # The custom domain is the only way in through API Gateway (the Function URL stays public).
  disable_execute_api_endpoint = true
}

resource "aws_lambda_permission" "api_gateway" {
  count = local.use_custom_domain ? 1 : 0

  statement_id  = "ApiGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.router.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.webhook[0].execution_arn}/*"
}

resource "aws_apigatewayv2_domain_name" "webhook" {
  count = local.use_custom_domain ? 1 : 0

  domain_name = local.webhook_fqdn

  domain_name_configuration {
    certificate_arn = aws_acm_certificate_validation.webhook[0].certificate_arn
    endpoint_type   = "REGIONAL"
    security_policy = "TLS_1_2"
  }
}

resource "aws_apigatewayv2_api_mapping" "webhook" {
  count = local.use_custom_domain ? 1 : 0

  api_id      = aws_apigatewayv2_api.webhook[0].id
  domain_name = aws_apigatewayv2_domain_name.webhook[0].id
  stage       = "$default"
}

resource "cloudflare_dns_record" "alias" {
  count = local.use_custom_domain ? 1 : 0

  zone_id = var.cloudflare_zone_id
  name    = local.webhook_fqdn
  type    = "CNAME"
  content = aws_apigatewayv2_domain_name.webhook[0].domain_name_configuration[0].target_domain_name
  ttl     = 60
  proxied = false
}
