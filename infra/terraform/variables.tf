variable "region" {
  description = "AWS 리전"
  type        = string
  default     = "ap-northeast-2"
}

variable "env" {
  description = "환경 이름 (dev/stage/prod)"
  type        = string
  default     = "dev"
}

variable "ssh_key_name" {
  description = "EC2 접속용 기존 EC2 key pair 이름 (없으면 빈 문자열 → SSM만 사용)"
  type        = string
  default     = ""
}

variable "uav_instance_type" {
  description = "온보드 UAV 모사 EC2 타입 (amd64, 2 vCPU / 4GB)"
  type        = string
  default     = "t3.medium"
}

variable "ground_instance_type" {
  description = "지상기지국 + 로그 서버 EC2 타입"
  type        = string
  default     = "t3.small"
}

variable "allowed_ssh_cidr" {
  description = "SSH(22) 허용 CIDR — 본인 IP/32 권장. 0.0.0.0/0 지양."
  type        = string
  default     = "0.0.0.0/0"
}

variable "ground_app_port" {
  description = "지상기지국(ground app) 노출 포트"
  type        = number
  default     = 8400
}

variable "log_server_port" {
  description = "실시간 로그 스트림 포트(log_server.py, 대시보드 연동)"
  type        = number
  default     = 8500
}

variable "raw_log_port" {
  description = "raw_log 수신 포트(main.py, uav→지상 비행후 업로드)"
  type        = number
  default     = 8181
}

variable "enable_cloudfront" {
  description = "대시보드 앞단 CloudFront 배포 사용 여부"
  type        = bool
  default     = false
}

variable "dashboard_domain" {
  description = "대시보드 커스텀 도메인 (FQDN)"
  type        = string
  default     = "uav.jubianix.com"
}

variable "dashboard_zone_name" {
  description = "대시보드 도메인이 속한 Route53 호스티드 존 이름"
  type        = string
  default     = "jubianix.com"
}

variable "github_org" {
  description = "GitHub OIDC assume 대상 org/owner (예: hobeen-kim)"
  type        = string
  default     = "hobeen-kim"
}

variable "github_repo" {
  description = "GitHub OIDC assume 대상 repo 이름"
  type        = string
  default     = "fried-mushroom-uav"
}

variable "uav_container_image" {
  description = "온보드 UAV 컨테이너 이미지 (기본은 ECR uav 리포지토리 latest)"
  type        = string
  default     = ""
}
