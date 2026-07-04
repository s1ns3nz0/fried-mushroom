# --- GitHub Actions OIDC — 키 없이 role assume ---
# GitHub 워크플로가 단기 토큰으로 이 role을 assume해 배포한다.
resource "aws_iam_openid_connect_provider" "github" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]
}

# 지정 repo(모든 브랜치)에서만 assume 허용.
data "aws_iam_policy_document" "github_assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    effect  = "Allow"

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_org}/${var.github_repo}:*"]
    }
  }
}

resource "aws_iam_role" "deploy" {
  name               = "fried-mushroom-uav-deploy-${var.env}"
  assume_role_policy = data.aws_iam_policy_document.github_assume.json
}

# 배포에 필요한 최소 권한: S3 배포 / ECR push / SSM send-command.
data "aws_iam_policy_document" "deploy" {
  # 대시보드 S3 배포
  statement {
    sid = "DashboardS3Deploy"
    actions = [
      "s3:ListBucket",
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
    ]
    resources = [
      aws_s3_bucket.dashboard.arn,
      "${aws_s3_bucket.dashboard.arn}/*",
    ]
  }

  # ECR 인증 토큰
  statement {
    sid       = "EcrAuth"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  # ECR push/pull (uav/ground/log 리포지토리)
  statement {
    sid = "EcrPush"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:CompleteLayerUpload",
      "ecr:InitiateLayerUpload",
      "ecr:PutImage",
      "ecr:UploadLayerPart",
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
    ]
    resources = [for r in aws_ecr_repository.this : r.arn]
  }

  # EC2에 배포 명령 전달 (SSM send-command)
  statement {
    sid = "SsmSendCommand"
    actions = [
      "ssm:SendCommand",
      "ssm:GetCommandInvocation",
      "ssm:ListCommandInvocations",
    ]
    resources = ["*"]
  }

  # 대상 인스턴스 조회 (배포 스크립트가 인스턴스 ID 확인)
  statement {
    sid       = "DescribeInstances"
    actions   = ["ec2:DescribeInstances"]
    resources = ["*"]
  }

  # CloudFront 무효화 (옵션)
  statement {
    sid       = "CloudFrontInvalidate"
    actions   = ["cloudfront:CreateInvalidation"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "deploy" {
  name   = "fried-mushroom-uav-deploy-${var.env}"
  role   = aws_iam_role.deploy.id
  policy = data.aws_iam_policy_document.deploy.json
}
