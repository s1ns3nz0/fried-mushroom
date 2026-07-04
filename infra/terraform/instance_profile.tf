# EC2가 SSM(Session Manager / send-command)과 ECR pull을 사용하도록 인스턴스 프로파일 부여.
# → 배포 워크플로가 SSH 키 없이 SSM으로 컨테이너를 갱신할 수 있다.
data "aws_iam_policy_document" "ec2_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ec2" {
  name               = "fried-mushroom-uav-ec2-${var.env}"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
}

# SSM Session Manager / send-command 기본 권한.
resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.ec2.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# ECR 이미지 pull(read-only) 권한.
resource "aws_iam_role_policy_attachment" "ecr_read" {
  role       = aws_iam_role.ec2.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
}

resource "aws_iam_instance_profile" "ec2" {
  name = "fried-mushroom-uav-ec2-${var.env}"
  role = aws_iam_role.ec2.name
}
