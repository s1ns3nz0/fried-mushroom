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
  description = "SSH(22) 허용 CIDR — 본인 공인 IP/32 필수. 0.0.0.0/0(전세계) 금지 (F-10 감사 #232)."
  type        = string
  # default 제거 — 명시 설정 강제(fail-closed). 세계개방 SSH 를 무설정으로 흘리지 않는다.

  validation {
    # SSH 는 단일 IPv4 호스트(/32)만 — /0·광역 범위·IPv6 차단. SG cidr_blocks 는 IPv4 전용이라
    # regex 로 IPv4 /32 형식 강제 + cidrhost 로 옥텟 유효성(0-255) 검증.
    condition     = can(cidrhost(var.allowed_ssh_cidr, 0)) && can(regex("^([0-9]{1,3}[.]){3}[0-9]{1,3}/32$", var.allowed_ssh_cidr))
    error_message = "allowed_ssh_cidr 는 유효 IPv4 /32(단일 호스트)여야 함 — 본인 공인 IP/32 지정."
  }
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

# F-02(DevSecOps 감사 #232): OIDC 배포 role 을 assume 할 수 있는 git ref 를 최소범위로 제한.
# 기본 main 브랜치 push 만 — PR/fork/타 브랜치의 role assume 를 차단(#208 노출 role 남용 방지).
variable "github_deploy_ref" {
  description = "배포 role assume 허용 git ref (sub 클레임). 기본: main 브랜치만"
  type        = string
  default     = "refs/heads/main"

  validation {
    condition     = can(regex("^refs/(heads|tags)/", var.github_deploy_ref))
    error_message = "github_deploy_ref 는 refs/heads/ 또는 refs/tags/ 로 시작해야 함 (와일드카드 금지)."
  }
}

variable "uav_container_image" {
  description = "온보드 UAV 컨테이너 이미지 (기본은 ECR uav 리포지토리 latest)"
  type        = string
  default     = ""
}
