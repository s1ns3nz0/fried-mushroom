terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # 원격 상태(S3 backend) — 팀 협업 시 주석 해제 후 값 채운다.
  # 버킷/키/DynamoDB 락 테이블은 사전에 생성되어 있어야 하며, 시크릿은 넣지 않는다.
  # backend는 변수 보간을 지원하지 않으므로 아래 값은 실제 배포 시 직접 채우거나
  # `terraform init -backend-config=...`로 주입한다.
  #
  # backend "s3" {
  #   bucket         = "fried-mushroom-uav-tfstate"   # 사전 생성된 상태 버킷
  #   key            = "infra/terraform.tfstate"      # 상태 파일 키
  #   region         = "ap-northeast-2"               # 상태 버킷 리전
  #   dynamodb_table = "fried-mushroom-uav-tflock"    # 상태 락 테이블
  #   encrypt        = true
  # }
}
