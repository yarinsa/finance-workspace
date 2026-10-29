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
  default     = "my-finance.yarinsa.me"
}

variable "hosted_zone_name" {
  description = "Existing public Route 53 zone that domain_name sits under."
  type        = string
  default     = "yarinsa.me"
}

variable "github_repo" {
  description = "owner/repo whose master branch may assume the CI deploy role."
  type        = string
  default     = "yarinsa/finance-workspace"
}

variable "github_owner_id" {
  description = "Numeric GitHub ID of the github_repo owner; part of the immutable OIDC subject. `gh api repos/<owner>/<repo> --jq .owner.id`"
  type        = string
  default     = "44482362"
}

variable "github_repo_id" {
  description = "Numeric GitHub ID of github_repo; part of the immutable OIDC subject. `gh api repos/<owner>/<repo> --jq .id`"
  type        = string
  default     = "1312600753"
}

variable "api_origin_domain" {
  description = "Tailscale Funnel hostname (<mac>.<tailnet>.ts.net) serving the ledger API. Empty disables everything API-related (origin, /api/* behavior, origin secret). Set by infra/tunnel.sh's instructions."
  type        = string
  default     = ""
}

variable "enforce_tenant_data" {
  description = "Require the master tenant's Cognito group (tenant-00000000-0000-4000-8000-000000000001) for /data/*.json. Keep false until infra/tenant-groups.sh has put every current user in it, then set true BEFORE onboarding a second tenant: until then any signed-in user can read the master tenant's files."
  type        = bool
  default     = false
}
