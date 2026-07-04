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

    # F-02(#232): sub 를 main 브랜치 ref 로 고정 — 와일드카드(:*)·environment subject 제거로
    # PR/fork/타 브랜치/workflow_dispatch 의 role assume 차단. (#271 HIGH: #270 이 추가한
    # :environment:production subject 는 브랜치 ref 가 없어 신뢰확대 → F-02 회귀라 롤백.)
    # 배포 job 의 environment: production 은 승인 리뷰 게이트 용도로만 유지. environment subject 를
    # 안전하게 신뢰하려면 github provider 로 deployment_branch_policy(main) 코드화 선행 필요(별도).
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_org}/${var.github_repo}:ref:${var.github_deploy_ref}"]
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

  # EC2에 배포 명령 전달 (SSM send-command) — F-04(#232): 대상 인스턴스 + 문서로 최소범위.
  statement {
    sid     = "SsmSendCommand"
    actions = ["ssm:SendCommand"]
    resources = [
      aws_instance.ground.arn,
      "arn:aws:ssm:${var.region}::document/AWS-RunShellScript",
    ]
  }

  # 명령 상태 조회는 command-invocation ID 가 동적이라 리소스 스코프 불가 → 읽기전용 * 유지.
  statement {
    sid = "SsmCommandStatus"
    actions = [
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

  # CloudFront 무효화 (옵션) — F-04(#232): 최소범위. enable_cloudfront 활성 시에만 권한 부여하고
  # 그 배포판 ARN 으로 스코프. 비활성 시 statement 자체를 생성하지 않음(불필요 권한 제거).
  dynamic "statement" {
    for_each = var.enable_cloudfront ? [1] : []
    content {
      sid       = "CloudFrontInvalidate"
      actions   = ["cloudfront:CreateInvalidation"]
      resources = [aws_cloudfront_distribution.dashboard[0].arn]
    }
  }
}

resource "aws_iam_role_policy" "deploy" {
  name   = "fried-mushroom-uav-deploy-${var.env}"
  role   = aws_iam_role.deploy.id
  policy = data.aws_iam_policy_document.deploy.json
}
