# 지상기지국 + 로그 서버 EC2 (docker-compose 2컨테이너)
locals {
  ecr_registry = "${data.aws_caller_identity.current.account_id}.dkr.ecr.${var.region}.amazonaws.com"
  ground_image = "${local.ecr_registry}/fried-mushroom-uav/ground:latest"
  # log repo 는 IMMUTABLE(F-05/#248)이라 :latest 를 push 하지 않는다. 이 값은 최초 부트
  # .env 플레이스홀더일 뿐이며, 첫 배포(deploy-log.yml)가 .env 의 LOG_IMAGE 를 불변
  # :${sha} 로 영속 갱신한다(이후 재부팅 시에도 그 SHA 를 사용). 즉 :latest 는 첫 배포
  # 전까지만의 임시값 — log 서비스는 첫 배포 후 기동된다.
  log_image = "${local.ecr_registry}/fried-mushroom-uav/log:latest"
  compose_file = file("${path.module}/templates/docker-compose.yml.tftpl")
}

resource "aws_instance" "ground" {
  ami                    = data.aws_ami.al2023.id
  instance_type          = var.ground_instance_type
  subnet_id              = local.public_subnet_id
  vpc_security_group_ids = [aws_security_group.ground.id]
  iam_instance_profile   = aws_iam_instance_profile.ec2.name
  key_name               = var.ssh_key_name != "" ? var.ssh_key_name : null

  associate_public_ip_address = true

  user_data = templatefile("${path.module}/templates/ground_user_data.sh.tftpl", {
    region          = var.region
    ecr_registry    = local.ecr_registry
    ground_image    = local.ground_image
    log_image       = local.log_image
    ground_app_port = var.ground_app_port
    log_server_port = var.log_server_port
    raw_log_port    = var.raw_log_port
    compose_file    = local.compose_file
  })

  metadata_options {
    http_tokens = "required" # IMDSv2 강제
  }

  root_block_device {
    volume_size = 20
    volume_type = "gp3"
    encrypted   = true
  }

  tags = { Name = "fried-mushroom-ground-${var.env}" }
}
