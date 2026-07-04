# UAV 온보드 EC2 보안 그룹 — SSH(허용 CIDR) + 아웃바운드 전체
resource "aws_security_group" "uav" {
  name        = "fried-mushroom-uav-${var.env}"
  description = "onboard UAV EC2 SG"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.allowed_ssh_cidr]
  }

  egress {
    description = "all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "fried-mushroom-uav-${var.env}" }
}

# 지상기지국 + 로그 서버 EC2 보안 그룹 — SSH + ground app/log 포트 + 아웃바운드 전체
resource "aws_security_group" "ground" {
  name        = "fried-mushroom-ground-${var.env}"
  description = "ground station + log server EC2 SG"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.allowed_ssh_cidr]
  }

  ingress {
    description = "ground app"
    from_port   = var.ground_app_port
    to_port     = var.ground_app_port
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "realtime log stream (dashboard)"
    from_port   = var.log_server_port
    to_port     = var.log_server_port
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "raw_log upload (uav to ground)"
    from_port   = var.raw_log_port
    to_port     = var.raw_log_port
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "fried-mushroom-ground-${var.env}" }
}
