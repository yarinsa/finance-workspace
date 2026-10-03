variable "region" {
  description = "Region for the S3 bucket and Cognito user pool. CloudFront, WAF and Lambda@Edge are pinned to us-east-1 regardless."
  type        = string
  default     = "us-east-1"
}

variable "owner_email" {
  description = "Email for the single Cognito user. Cognito sends a temporary password here on first apply."
  type        = string
}
