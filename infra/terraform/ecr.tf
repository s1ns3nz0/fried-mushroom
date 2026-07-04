# uav / ground / log 컨테이너 이미지를 담을 ECR 리포지토리.
locals {
  ecr_repos = ["uav", "ground", "log"]
}

resource "aws_ecr_repository" "this" {
  for_each = toset(local.ecr_repos)

  name = "fried-mushroom-uav/${each.key}"
  # 감사 F-05(#248): IMMUTABLE — 동일 태그(특히 :${sha}) 사후 덮어쓰기 금지로
  # "이 SHA = 이 이미지" 추적성 보장. 이동태그 :latest 는 push 하지 않고 배포는 SHA 로
  # 핀한다(deploy-log.yml). provider v5.100.0 은 latest 예외(exclusion_filter) 미지원.
  image_tag_mutability = "IMMUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = { Name = "fried-mushroom-uav-${each.key}" }
}

# 오래된 이미지 정리 — 최근 10개만 보관.
resource "aws_ecr_lifecycle_policy" "this" {
  for_each   = aws_ecr_repository.this
  repository = each.value.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "keep last 10 images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = { type = "expire" }
    }]
  })
}
