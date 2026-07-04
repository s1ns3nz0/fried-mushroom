# 대시보드 CloudFront 커스텀 도메인(HTTPS)용 ACM 인증서 + Route53 레코드.
# enable_cloudfront=true 일 때만 생성된다.

data "aws_route53_zone" "dashboard" {
  count        = var.enable_cloudfront ? 1 : 0
  name         = "${var.dashboard_zone_name}."
  private_zone = false
}

# CloudFront가 사용하는 ACM 인증서는 반드시 us-east-1 리전이어야 한다.
resource "aws_acm_certificate" "dashboard" {
  count             = var.enable_cloudfront ? 1 : 0
  provider          = aws.us_east_1
  domain_name       = var.dashboard_domain
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_route53_record" "cert_validation" {
  count           = var.enable_cloudfront ? 1 : 0
  allow_overwrite = true
  ttl             = 60
  zone_id         = data.aws_route53_zone.dashboard[0].zone_id
  name            = tolist(aws_acm_certificate.dashboard[0].domain_validation_options)[0].resource_record_name
  type            = tolist(aws_acm_certificate.dashboard[0].domain_validation_options)[0].resource_record_type
  records         = [tolist(aws_acm_certificate.dashboard[0].domain_validation_options)[0].resource_record_value]
}

resource "aws_acm_certificate_validation" "dashboard" {
  count                   = var.enable_cloudfront ? 1 : 0
  provider                = aws.us_east_1
  certificate_arn         = aws_acm_certificate.dashboard[0].arn
  validation_record_fqdns = [aws_route53_record.cert_validation[0].fqdn]
}

resource "aws_route53_record" "dashboard_alias" {
  count   = var.enable_cloudfront ? 1 : 0
  zone_id = data.aws_route53_zone.dashboard[0].zone_id
  name    = var.dashboard_domain
  type    = "A"

  alias {
    name                   = aws_cloudfront_distribution.dashboard[0].domain_name
    zone_id                = aws_cloudfront_distribution.dashboard[0].hosted_zone_id
    evaluate_target_health = false
  }
}
