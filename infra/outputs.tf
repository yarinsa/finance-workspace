output "url" {
  description = "The dashboard. Hitting it redirects to the Cognito login until a session cookie exists."
  value       = "https://${aws_cloudfront_distribution.site.domain_name}"
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
  description = "Cognito hosted UI domain."
  value       = "${aws_cognito_user_pool_domain.users.domain}.auth.${var.region}.amazoncognito.com"
}

output "user_pool_id" {
  description = "Cognito user pool id, for managing users via the CLI."
  value       = aws_cognito_user_pool.users.id
}
