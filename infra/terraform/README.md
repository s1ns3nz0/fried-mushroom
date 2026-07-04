# fried-mushroom-uav — Terraform 인프라

D4D UAV 시스템의 AWS 인프라(IaC). **이 코드는 실제 apply하지 않은 정의만** 포함한다.
사용자가 **본인 AWS 계정에서 직접 `init`/`plan` 후 `apply`** 한다(private 계정).

## 리소스 개요

| 구성 | 리소스 | 비고 |
|------|--------|------|
| 온보드 UAV | `aws_instance.uav` | AL2023 amd64, `t3.medium`(2 vCPU/4GB), Docker + 컨테이너 `--cpus=2 --memory=4g` |
| 대시보드 | `aws_s3_bucket.dashboard` (+옵션 CloudFront) | `infra/dashboard/static` 정적 호스팅 |
| 지상기지국+로그 | `aws_instance.ground` | Docker Compose 2컨테이너(ground app / log collector) |
| 컨테이너 레지스트리 | `aws_ecr_repository` × 3 | `uav` / `ground` / `log` |
| CI/CD 인증 | GitHub OIDC provider + `aws_iam_role.deploy` | 키 없이 role assume |

AMI는 `data aws_ami`로 AL2023 x86_64를 lookup(하드코딩 없음). 계정ID·키는 코드에 없음.

## 사전 준비

1. AWS 계정 + `terraform` >= 1.5, AWS 자격 증명(로컬 `plan`/`apply` 시).
2. (원격 상태 쓸 경우) 상태용 S3 버킷·DynamoDB 락 테이블 생성 후 `versions.tf`의 backend 주석 해제.
3. `terraform.tfvars` 작성:
   ```bash
   cp terraform.tfvars.example terraform.tfvars
   # allowed_ssh_cidr 를 본인 IP/32 로, github_org/repo 를 실제 값으로 수정
   ```

## 배포 순서

```bash
cd infra/terraform
terraform init
terraform plan      # 변경 검토
terraform apply     # 실제 리소스 생성 (사용자 판단 하에)
```

문법만 검증(자격 증명 불필요):

```bash
terraform fmt -check -recursive
terraform init -backend=false && terraform validate
```

## 배포 후 — GitHub 저장소에 설정할 값

`terraform output`으로 값 확인 후 GitHub repo에 등록한다.

### Secrets
| 이름 | 값 | 출처 |
|------|-----|------|
| `AWS_ROLE_ARN` | 배포 role ARN | `terraform output deploy_role_arn` |

### Variables (repo variables)
| 이름 | 값 | 출처 |
|------|-----|------|
| `AWS_REGION` | 리전 (예: `ap-northeast-2`) | `var.region` |
| `DASHBOARD_BUCKET` | 대시보드 버킷 | `terraform output dashboard_bucket` |
| `UAV_INSTANCE_ID` | UAV EC2 ID | `terraform output uav_instance_id` |
| `GROUND_INSTANCE_ID` | 지상 EC2 ID | `terraform output ground_instance_id` |
| `CLOUDFRONT_DISTRIBUTION_ID` | (옵션) CloudFront ID | CloudFront 활성 시 |

> `github_org`/`github_repo` 변수가 OIDC assume 조건(`repo:ORG/REPO:*`)을 만든다.
> 다른 repo에서는 이 role을 assume할 수 없다.

## 워크플로 (`.github/workflows/`)
- `terraform.yml` — PR: fmt+validate+plan / main push: apply
- `deploy-dashboard.yml` — `infra/dashboard/**` 변경 → S3 sync (+CloudFront invalidation)
- `deploy-uav.yml` — `uav/**` 변경 → ECR push → SSM으로 온보드 컨테이너 재기동(cpus=2/mem 4g)
- `deploy-ground.yml` — `ground/**`·`infra/log/**` 변경 → ECR push → SSM으로 compose pull/up

모든 워크플로는 OIDC(`aws-actions/configure-aws-credentials@v4`)로 role을 assume — **하드코딩 키 없음.**

## 주의 (private 계정)
- `apply`는 실제 과금 리소스(EC2 2대, S3, ECR, 옵션 CloudFront)를 생성한다.
- `allowed_ssh_cidr`를 `0.0.0.0/0`으로 두지 말 것 — 본인 IP로 좁힌다.
- 정리: `terraform destroy` (S3/ECR는 `force_destroy`/`force_delete`로 비어있지 않아도 삭제됨).
