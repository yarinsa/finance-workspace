output "url" {
  description = "The dashboard. Hitting it redirects to the Cognito login until a session cookie exists."
  value       = "https://${var.domain_name}"
}

output "passkey_url" {
  description = "Open while signed in to enrol a passkey (Face ID / Touch ID / security key)."
  value       = "https://${var.domain_name}/_passkey"
}

output "bucket" {
  description = "Private S3 bucket holding the app bundle and the digested JSON."
  value       = aws_s3_bucket.site.id
}

output "distribution_id" {
  description = "Needed for cache invalidation after an upload."
  value       = aws_cloudfront_distribution.site.id
}

output "login_domain" {
  description = "Cognito managed login domain (passkey relying party)."
  value       = local.auth_domain
}

output "user_pool_id" {
  description = "Cognito user pool id, for managing users via the CLI."
  value       = aws_cognito_user_pool.users.id
}

output "github_deploy_role_arn" {
  description = "Role GitHub Actions assumes (OIDC) to publish the app bundle. Set as the AWS_DEPLOY_ROLE_ARN repo variable."
  value       = aws_iam_role.github_deploy.arn
}

output "api_origin_secret" {
  description = "Shared secret CloudFront sends as X-Origin-Secret. Copy to .env as FINANCE_API_ORIGIN_SECRET: `terraform output -raw api_origin_secret`. Empty while api_origin_domain is unset."
  value       = try(random_password.api_origin_secret[0].result, "")
  sensitive   = true
}

output "domain_name" {
  description = "Public domain; invite emails are sent from noreply@ it."
  value       = var.domain_name
}

output "client_id" {
  description = "Cognito app client id, for the invite sign-in link."
  value       = aws_cognito_user_pool_client.web.id
}
