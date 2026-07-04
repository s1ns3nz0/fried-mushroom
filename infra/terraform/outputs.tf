output "uav_public_ip" {
  description = "온보드 UAV EC2 퍼블릭 IP"
  value       = aws_instance.uav.public_ip
}

output "uav_instance_id" {
  description = "온보드 UAV EC2 인스턴스 ID (SSM 대상)"
  value       = aws_instance.uav.id
}

output "ground_public_ip" {
  description = "지상기지국 + 로그 서버 EC2 퍼블릭 IP"
  value       = aws_instance.ground.public_ip
}

output "ground_instance_id" {
  description = "지상 EC2 인스턴스 ID (SSM 대상)"
  value       = aws_instance.ground.id
}

output "dashboard_bucket" {
  description = "대시보드 정적 호스팅 S3 버킷 이름"
  value       = aws_s3_bucket.dashboard.bucket
}

output "dashboard_url" {
  description = "대시보드 접속 URL (CloudFront 사용 시 CDN 도메인)"
  value       = var.enable_cloudfront ? "https://${aws_cloudfront_distribution.dashboard[0].domain_name}" : "http://${aws_s3_bucket_website_configuration.dashboard.website_endpoint}"
}

output "dashboard_custom_domain" {
  description = "대시보드 커스텀 도메인 URL (enable_cloudfront=true 일 때만)"
  value       = var.enable_cloudfront ? "https://${var.dashboard_domain}" : null
}

output "deploy_role_arn" {
  description = "GitHub Actions가 assume할 배포 role ARN (AWS_ROLE_ARN 시크릿)"
  value       = aws_iam_role.deploy.arn
}

output "ecr_repositories" {
  description = "ECR 리포지토리 URL (uav/ground/log)"
  value       = { for k, r in aws_ecr_repository.this : k => r.repository_url }
}
