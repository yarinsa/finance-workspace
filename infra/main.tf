// Plangram dashboard hosting.
//
// The thing this protects: data/digested/*.json is the household's complete
// financial record — account numbers, every transaction, loan balances, pension.
// So the design rule is that NOTHING is reachable without authenticating first:
// the bucket is private (no website hosting, no public ACLs), CloudFront reaches
// it only via OAC, and a Lambda@Edge viewer-request check rejects any request
// that does not carry a valid Cognito session.
//
// WAF is deliberately NOT the access control here — it rate-limits and blocks
// known-bad patterns, which is defence in depth, not authentication.

terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.40"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
    null = {
      source  = "hashicorp/null"
      version = "~> 3.2"
    }
  }
}

provider "aws" {
  region = var.region
}

// CloudFront, WAF (scope CLOUDFRONT) and Lambda@Edge must all live in us-east-1
// regardless of where the bucket is.
provider "aws" {
  alias  = "edge"
  region = "us-east-1"
}

data "aws_caller_identity" "current" {}

resource "random_id" "suffix" {
  byte_length = 4
}

locals {
  name   = "plangram"
  bucket = "${local.name}-${random_id.suffix.hex}"

  tags = {
    Project = "plangram"
    Owner   = "yarinsa"
    Managed = "terraform"
  }
}

# ──────────────────────────────── S3 ────────────────────────────────

resource "aws_s3_bucket" "site" {
  bucket = local.bucket
  tags   = local.tags
}

// Every public-access vector off. This bucket holds financial records; there is
// no scenario in this project where public access is correct.
resource "aws_s3_bucket_public_access_block" "site" {
  bucket                  = aws_s3_bucket.site.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "site" {
  bucket = aws_s3_bucket.site.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "site" {
  bucket = aws_s3_bucket.site.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_ownership_controls" "site" {
  bucket = aws_s3_bucket.site.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

// Only this distribution may read, and only via OAC.
data "aws_iam_policy_document" "bucket" {
  statement {
    sid       = "AllowCloudFrontOAC"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.site.arn}/*"]

    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.site.arn]
    }
  }

  // Belt and braces: refuse anything not over TLS.
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.site.arn, "${aws_s3_bucket.site.arn}/*"]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "site" {
  bucket     = aws_s3_bucket.site.id
  policy     = data.aws_iam_policy_document.bucket.json
  depends_on = [aws_s3_bucket_public_access_block.site]
}

# ─────────────────────────────── Cognito ───────────────────────────────

resource "aws_cognito_user_pool" "users" {
  name                     = "${local.name}-users"
  deletion_protection      = "ACTIVE"
  mfa_configuration        = "OPTIONAL"
  auto_verified_attributes = ["email"]

  software_token_mfa_configuration {
    enabled = true
  }

  password_policy {
    minimum_length                   = 14
    require_lowercase                = true
    require_uppercase                = true
    require_numbers                  = true
    require_symbols                  = true
    temporary_password_validity_days = 1
  }

  // No self-signup: this pool has exactly one intended human.
  admin_create_user_config {
    allow_admin_create_user_only = true
  }

  tags = local.tags
}

resource "aws_cognito_user_pool_domain" "users" {
  domain       = "${local.name}-${random_id.suffix.hex}"
  user_pool_id = aws_cognito_user_pool.users.id
}

resource "aws_cognito_user_pool_client" "web" {
  name         = "${local.name}-web"
  user_pool_id = aws_cognito_user_pool.users.id

  generate_secret                      = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_scopes                 = ["openid", "email"]
  supported_identity_providers         = ["COGNITO"]

  // Chicken-and-egg: the real callback is https://<cloudfront-domain>/_callback,
  // but CloudFront depends on the Lambda, which depends on this client's secret.
  // So the client is created with a placeholder and the real URLs are patched in
  // by the aws_cognito_user_pool_client_urls null_resource below, once the
  // distribution exists. `lifecycle.ignore_changes` stops Terraform from
  // reverting that patch on the next plan.
  callback_urls = ["https://localhost/_callback"]
  logout_urls   = ["https://localhost/"]

  lifecycle {
    ignore_changes = [callback_urls, logout_urls]
  }

  // Short-lived sessions: this is financial data on a device that may be shared.
  access_token_validity  = 60
  id_token_validity      = 60
  refresh_token_validity = 1
  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "days"
  }

  explicit_auth_flows = ["ALLOW_REFRESH_TOKEN_AUTH", "ALLOW_USER_SRP_AUTH"]
}

// Patch the real callback/logout URLs in once CloudFront exists. This is the
// second half of the placeholder above; without it the OAuth redirect_uri will
// not match and login fails with redirect_mismatch.
resource "null_resource" "cognito_urls" {
  triggers = {
    client_id = aws_cognito_user_pool_client.web.id
    domain    = aws_cloudfront_distribution.site.domain_name
  }

  provisioner "local-exec" {
    command = <<-CMD
      aws cognito-idp update-user-pool-client \
        --region ${var.region} \
        --user-pool-id ${aws_cognito_user_pool.users.id} \
        --client-id ${aws_cognito_user_pool_client.web.id} \
        --client-name ${local.name}-web \
        --callback-urls "https://${aws_cloudfront_distribution.site.domain_name}/_callback" \
        --logout-urls "https://${aws_cloudfront_distribution.site.domain_name}/" \
        --allowed-o-auth-flows code \
        --allowed-o-auth-scopes openid email \
        --allowed-o-auth-flows-user-pool-client \
        --supported-identity-providers COGNITO \
        --explicit-auth-flows ALLOW_REFRESH_TOKEN_AUTH ALLOW_USER_SRP_AUTH \
        --access-token-validity 60 --id-token-validity 60 --refresh-token-validity 1 \
        --token-validity-units AccessToken=minutes,IdToken=minutes,RefreshToken=days \
        --output text > /dev/null
    CMD
  }
}

resource "aws_cognito_user" "owner" {
  user_pool_id = aws_cognito_user_pool.users.id
  username     = var.owner_email

  attributes = {
    email          = var.owner_email
    email_verified = "true"
  }

  // Cognito emails a temporary password; it must be changed on first sign-in.
  desired_delivery_mediums = ["EMAIL"]
}

# ──────────────────────── Lambda@Edge auth gate ────────────────────────

data "aws_iam_policy_document" "edge_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com", "edgelambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "edge_auth" {
  name               = "${local.name}-edge-auth"
  assume_role_policy = data.aws_iam_policy_document.edge_assume.json
  tags               = local.tags
}

resource "aws_iam_role_policy_attachment" "edge_auth_logs" {
  role       = aws_iam_role.edge_auth.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

// Config the edge function needs, baked in at build time: Lambda@Edge cannot
// read environment variables, so these are templated into the source.
locals {
  edge_config = {
    region        = var.region
    user_pool_id  = aws_cognito_user_pool.users.id
    client_id     = aws_cognito_user_pool_client.web.id
    client_secret = aws_cognito_user_pool_client.web.client_secret
    hosted_domain = "${aws_cognito_user_pool_domain.users.domain}.auth.${var.region}.amazoncognito.com"
    cookie_name   = "plangram_session"
  }
}

data "archive_file" "edge_auth" {
  type        = "zip"
  output_path = "${path.module}/.build/edge-auth.zip"

  source {
    filename = "index.js"
    content = templatefile("${path.module}/edge-auth/index.js.tftpl", {
      config_json = jsonencode(local.edge_config)
    })
  }
}

resource "aws_lambda_function" "edge_auth" {
  provider = aws.edge

  function_name    = "${local.name}-edge-auth"
  role             = aws_iam_role.edge_auth.arn
  handler          = "index.handler"
  runtime          = "nodejs20.x"
  filename         = data.archive_file.edge_auth.output_path
  source_code_hash = data.archive_file.edge_auth.output_base64sha256
  publish          = true
  timeout          = 5
  memory_size      = 128

  tags = local.tags
}

# ───────────────────────────────── WAF ─────────────────────────────────

// Defence in depth only. The access decision is made by the edge auth function;
// this layer throttles abuse and blocks known-bad request shapes.
resource "aws_wafv2_web_acl" "site" {
  provider = aws.edge

  name        = "${local.name}-acl"
  description = "Rate limiting and managed rules for the Plangram dashboard"
  scope       = "CLOUDFRONT"

  default_action {
    allow {}
  }

  rule {
    name     = "RateLimit"
    priority = 1

    action {
      block {}
    }

    statement {
      rate_based_statement {
        limit              = 500
        aggregate_key_type = "IP"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "RateLimit"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "CommonRuleSet"
    priority = 2

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesCommonRuleSet"
        vendor_name = "AWS"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "CommonRuleSet"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "KnownBadInputs"
    priority = 3

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesKnownBadInputsRuleSet"
        vendor_name = "AWS"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "KnownBadInputs"
      sampled_requests_enabled   = true
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "${local.name}-acl"
    sampled_requests_enabled   = true
  }

  tags = local.tags
}

# ───────────────────────────── CloudFront ─────────────────────────────

resource "aws_cloudfront_origin_access_control" "site" {
  name                              = "${local.name}-oac"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_distribution" "site" {
  enabled             = true
  comment             = "Plangram finance dashboard (auth-gated)"
  default_root_object = "index.html"
  price_class         = "PriceClass_100"
  web_acl_id          = aws_wafv2_web_acl.site.arn

  origin {
    domain_name              = aws_s3_bucket.site.bucket_regional_domain_name
    origin_id                = "s3"
    origin_access_control_id = aws_cloudfront_origin_access_control.site.id
  }

  default_cache_behavior {
    target_origin_id       = "s3"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD", "OPTIONS"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true

    // CachingDisabled. Caching an authenticated response at the edge risks
    // serving one viewer's data to another; the payload is <1MB so there is
    // nothing to gain by caching it.
    cache_policy_id = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"

    lambda_function_association {
      event_type   = "viewer-request"
      lambda_arn   = aws_lambda_function.edge_auth.qualified_arn
      include_body = false
    }
  }

  // SPA routing: unknown paths return index.html so client-side routes work.
  // 403 is what a private S3 origin returns for a missing key.
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
    cloudfront_default_certificate = true
    minimum_protocol_version       = "TLSv1.2_2021"
  }

  tags = local.tags
}
