# 대시보드 정적 웹 호스팅 — infra/dashboard/static 배포 대상.
# 기본: S3 정적 웹사이트 호스팅(public read).
# enable_cloudfront=true: 버킷은 private 유지, CloudFront + OAC로만 접근.

resource "aws_s3_bucket" "dashboard" {
  bucket_prefix = "fried-mushroom-uav-dashboard-"
  force_destroy = true

  tags = { Name = "fried-mushroom-uav-dashboard-${var.env}" }
}

resource "aws_s3_bucket_website_configuration" "dashboard" {
  bucket = aws_s3_bucket.dashboard.id

  index_document {
    suffix = "index.html"
  }

  error_document {
    key = "index.html"
  }
}

# CloudFront 미사용 시에만 퍼블릭 접근 허용.
resource "aws_s3_bucket_public_access_block" "dashboard" {
  bucket = aws_s3_bucket.dashboard.id

  block_public_acls       = var.enable_cloudfront
  block_public_policy     = var.enable_cloudfront
  ignore_public_acls      = var.enable_cloudfront
  restrict_public_buckets = var.enable_cloudfront
}

# --- CloudFront 미사용: 퍼블릭 read 정책 ---
data "aws_iam_policy_document" "dashboard_public" {
  count = var.enable_cloudfront ? 0 : 1

  statement {
    sid       = "PublicReadGetObject"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.dashboard.arn}/*"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
  }
}

# --- CloudFront 사용: OAC 경유만 허용 ---
data "aws_iam_policy_document" "dashboard_oac" {
  count = var.enable_cloudfront ? 1 : 0

  statement {
    sid       = "AllowCloudFrontOAC"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.dashboard.arn}/*"]
    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.dashboard[0].arn]
    }
  }
}

resource "aws_s3_bucket_policy" "dashboard" {
  bucket = aws_s3_bucket.dashboard.id
  policy = var.enable_cloudfront ? data.aws_iam_policy_document.dashboard_oac[0].json : data.aws_iam_policy_document.dashboard_public[0].json

  depends_on = [aws_s3_bucket_public_access_block.dashboard]
}

# --- CloudFront (옵션) ---
resource "aws_cloudfront_origin_access_control" "dashboard" {
  count = var.enable_cloudfront ? 1 : 0

  name                              = "fried-mushroom-uav-dashboard-${var.env}"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_distribution" "dashboard" {
  count = var.enable_cloudfront ? 1 : 0

  enabled             = true
  default_root_object = "index.html"
  aliases             = [var.dashboard_domain]

  origin {
    domain_name              = aws_s3_bucket.dashboard.bucket_regional_domain_name
    origin_id                = "dashboard-s3"
    origin_access_control_id = aws_cloudfront_origin_access_control.dashboard[0].id
  }

  default_cache_behavior {
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = "dashboard-s3"
    viewer_protocol_policy = "redirect-to-https"

    forwarded_values {
      query_string = false
      cookies {
        forward = "none"
      }
    }
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    acm_certificate_arn      = aws_acm_certificate_validation.dashboard[0].certificate_arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }

  tags = { Name = "fried-mushroom-uav-dashboard-${var.env}" }
}
