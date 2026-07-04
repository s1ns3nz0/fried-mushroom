# 온보드 UAV 모사 EC2 (amd64 / AL2023 / t3.medium = 2 vCPU · 4GB)
resource "aws_instance" "uav" {
  ami                    = data.aws_ami.al2023.id
  instance_type          = var.uav_instance_type
  subnet_id              = local.public_subnet_id
  vpc_security_group_ids = [aws_security_group.uav.id]
  iam_instance_profile   = aws_iam_instance_profile.ec2.name
  key_name               = var.ssh_key_name != "" ? var.ssh_key_name : null

  associate_public_ip_address = true

  user_data = templatefile("${path.module}/templates/uav_user_data.sh.tftpl", {
    region       = var.region
    ecr_registry = "${data.aws_caller_identity.current.account_id}.dkr.ecr.${var.region}.amazonaws.com"
    uav_image    = var.uav_container_image
  })

  metadata_options {
    http_tokens = "required" # IMDSv2 강제
  }

  root_block_device {
    volume_size = 20
    volume_type = "gp3"
    encrypted   = true
  }

  tags = { Name = "fried-mushroom-uav-onboard-${var.env}" }
}
