# Amazon Linux 2023 (x86_64 / amd64) 최신 AMI — 하드코딩 금지, lookup 사용.
data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-2023.*-x86_64"]
  }

  filter {
    name   = "architecture"
    values = ["x86_64"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

# 현재 계정/파티션 — ARN 조립 및 OIDC sub 구성에 사용.
data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}
