provider "aws" {
  region = var.region

  # 모든 리소스에 공통 태그 부착 — 비용 추적/정리에 사용.
  default_tags {
    tags = {
      project = "fried-mushroom-uav"
      env     = var.env
      managed = "terraform"
    }
  }
}

# CloudFront용 ACM 인증서는 반드시 us-east-1 리전에 있어야 한다.
provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"

  default_tags {
    tags = {
      project = "fried-mushroom-uav"
      env     = var.env
      managed = "terraform"
    }
  }
}
