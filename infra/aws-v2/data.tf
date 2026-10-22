data "aws_caller_identity" "current" {}
data "aws_availability_zones" "available" { state = "available" }

# V1 (solo lectura): VPC, subred pública de la primera zona, tabla de rutas pública y grupo de seguridad de la base.
data "aws_vpc" "v1" {
  filter {
    name   = "tag:Name"
    values = ["${local.name_prefix}-vpc"]
  }
}

data "aws_subnet" "public_a" {
  filter {
    name   = "tag:Name"
    values = ["${local.name_prefix}-public-a"]
  }
  vpc_id = data.aws_vpc.v1.id
}

data "aws_route_table" "public" {
  filter {
    name   = "tag:Name"
    values = ["${local.name_prefix}-public-rt"]
  }
  vpc_id = data.aws_vpc.v1.id
}

data "aws_security_group" "database" {
  filter {
    name   = "tag:Name"
    values = ["${local.name_prefix}-db-sg"]
  }
  vpc_id = data.aws_vpc.v1.id
}

data "aws_iam_instance_profile" "app" {
  name = var.instance_profile_name
}
