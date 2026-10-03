variable "region" {
  description = "Region for the S3 bucket and Cognito user pool. CloudFront, WAF and Lambda@Edge are pinned to us-east-1 regardless."
  type        = string
  default     = "us-east-1"
}

variable "owner_email" {
  description = "Email for the single Cognito user. Cognito sends a temporary password here on first apply."
  type        = string
}

variable "domain_name" {
  description = "Public hostname for the dashboard. The Cognito login lives on auth.<domain_name>."
  type        = string
  default     = "finance.yarinsa.me"
}

variable "hosted_zone_name" {
  description = "Existing public Route 53 zone that domain_name sits under."
  type        = string
  default     = "yarinsa.me"
}
