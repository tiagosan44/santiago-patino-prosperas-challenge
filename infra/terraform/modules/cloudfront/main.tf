# CloudFront distribution in front of the frontend S3 bucket.
# Uses Origin Access Control (the modern replacement for OAI) so the
# bucket can stay private while CloudFront has access.

resource "aws_cloudfront_origin_access_control" "frontend" {
  name                              = "${var.project_name}-frontend-oac"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_distribution" "frontend" {
  enabled             = true
  is_ipv6_enabled     = true
  default_root_object = "index.html"
  comment             = "${var.project_name}-frontend"
  price_class         = "PriceClass_100" # NA + EU only — cheapest

  origin {
    origin_id                = "frontend-s3"
    domain_name              = var.frontend_bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.frontend.id
  }

  # API ALB as second origin (HTTP backend; CloudFront terminates TLS).
  # Lets the browser hit https://<cloudfront>/auth/... instead of plain
  # http://<alb>/auth/... — fixes Mixed Content because everything is
  # same-origin HTTPS from the browser's perspective.
  origin {
    origin_id   = "api-alb"
    domain_name = var.alb_dns_name

    custom_origin_config {
      http_port                = 80
      https_port               = 443
      origin_protocol_policy   = "http-only" # backend is HTTP; only CloudFront <-> ALB hop is HTTP
      origin_ssl_protocols     = ["TLSv1.2"]
      origin_read_timeout      = 60 # SSE keepalives every 15s; need > that
      origin_keepalive_timeout = 60
    }
  }

  default_cache_behavior {
    target_origin_id       = "frontend-s3"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true

    forwarded_values {
      query_string = false
      cookies {
        forward = "none"
      }
    }

    min_ttl     = 0
    default_ttl = 300
    max_ttl     = 86400
  }

  # API behaviors — pass everything through, no caching.
  # Order matters: more specific paths first; CloudFront uses first-match.
  dynamic "ordered_cache_behavior" {
    for_each = ["/auth/*", "/jobs", "/jobs/*", "/events/*", "/health", "/openapi.json", "/docs", "/docs/*"]
    content {
      path_pattern           = ordered_cache_behavior.value
      target_origin_id       = "api-alb"
      viewer_protocol_policy = "redirect-to-https"
      allowed_methods        = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
      cached_methods         = ["GET", "HEAD"]
      compress               = false # SSE must NOT be buffered/gzipped at CloudFront

      forwarded_values {
        query_string = true
        headers      = ["Authorization", "Accept", "Content-Type", "Origin", "Host"]
        cookies {
          forward = "all"
        }
      }

      min_ttl     = 0
      default_ttl = 0
      max_ttl     = 0
    }
  }

  # SPA routing: 403/404 from S3 -> serve index.html with 200
  custom_error_response {
    error_code            = 403
    response_code         = 200
    response_page_path    = "/index.html"
    error_caching_min_ttl = 0
  }

  custom_error_response {
    error_code            = 404
    response_code         = 200
    response_page_path    = "/index.html"
    error_caching_min_ttl = 0
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true # *.cloudfront.net cert
  }

  tags = {
    Name = "${var.project_name}-frontend"
  }
}

# Bucket policy that allows CloudFront (via OAC) to read the bucket.

data "aws_iam_policy_document" "frontend" {
  statement {
    sid       = "AllowCloudFrontOAC"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["${var.frontend_bucket_arn}/*"]

    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.frontend.arn]
    }
  }
}

resource "aws_s3_bucket_policy" "frontend" {
  bucket = var.frontend_bucket_id
  policy = data.aws_iam_policy_document.frontend.json
}
