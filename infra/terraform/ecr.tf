# uav / ground / log 컨테이너 이미지를 담을 ECR 리포지토리.
locals {
  ecr_repos = ["uav", "ground", "log"]
  # 감사 F-05(#248/#278 후속): IMMUTABLE 은 **SHA 태그 배포 경로가 있는 repo(log)만** 적용.
  # deploy-log.yml 이 log 를 불변 :${sha} 로 push/핀하므로 IMMUTABLE 이 추적성을 보장한다.
  # uav/ground 는 아직 :latest 참조(ground bootstrap `ground:latest`, uav 예시 `uav:latest`)
  # + 전용 SHA 배포 워크플로 부재 → MUTABLE 유지(전체 IMMUTABLE 시 latest 재push 동결).
  # 각 repo 에 SHA 배포 도입 시 immutable_ecr_repos 에 추가한다.
  immutable_ecr_repos = ["log"]
}

resource "aws_ecr_repository" "this" {
  for_each = toset(local.ecr_repos)

  name                 = "fried-mushroom-uav/${each.key}"
  image_tag_mutability = contains(local.immutable_ecr_repos, each.key) ? "IMMUTABLE" : "MUTABLE"
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
