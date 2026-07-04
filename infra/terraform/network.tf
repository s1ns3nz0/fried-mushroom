# 단순화를 위해 기존 default VPC / 퍼블릭 서브넷을 사용한다.
# (전용 VPC가 필요하면 aws_vpc/aws_subnet/aws_internet_gateway로 교체)

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "public" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

# 인스턴스 배치에 사용할 첫 번째 퍼블릭 서브넷.
locals {
  public_subnet_id = tolist(data.aws_subnets.public.ids)[0]
}
