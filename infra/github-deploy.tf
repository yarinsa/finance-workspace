// CI deploy role: lets GitHub Actions on master publish the app bundle, and
// nothing else. Auth is OIDC — no long-lived AWS keys stored in GitHub.
//
// Deliberately NOT granted: s3:GetObject. CI only ever writes the bundle; it
// has no reason to read the bucket, which also holds data/*.json (the
// household's financial record). ListBucket is the minimum `aws s3 sync
// --delete` needs to diff; DeleteObject is scoped away from data/* so a
// misbehaving sync can never remove the published data.

// The account-wide GitHub OIDC provider already exists (one per account), so
// reference it instead of owning it here.
data "aws_iam_openid_connect_provider" "github" {
  url = "https://token.actions.githubusercontent.com"
}

data "aws_iam_policy_document" "github_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [data.aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    // Only the master branch of this repo — not PRs, not forks, not tags.
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repo}:ref:refs/heads/master"]
    }
  }
}

resource "aws_iam_role" "github_deploy" {
  name                 = "${local.name}-github-deploy"
  assume_role_policy   = data.aws_iam_policy_document.github_assume.json
  max_session_duration = 3600
  tags                 = local.tags
}

data "aws_iam_policy_document" "github_deploy" {
  statement {
    sid       = "ListForSync"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.site.arn]
  }

  statement {
    sid       = "WriteBundle"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.site.arn}/*"]
  }

  statement {
    sid       = "PruneOldBundle"
    actions   = ["s3:DeleteObject"]
    resources = ["${aws_s3_bucket.site.arn}/*"]
  }

  statement {
    sid       = "NeverTouchData"
    effect    = "Deny"
    actions   = ["s3:PutObject", "s3:DeleteObject", "s3:GetObject"]
    resources = ["${aws_s3_bucket.site.arn}/data/*"]
  }

  statement {
    sid       = "Invalidate"
    actions   = ["cloudfront:CreateInvalidation"]
    resources = [aws_cloudfront_distribution.site.arn]
  }
}

resource "aws_iam_role_policy" "github_deploy" {
  name   = "deploy-bundle"
  role   = aws_iam_role.github_deploy.id
  policy = data.aws_iam_policy_document.github_deploy.json
}
