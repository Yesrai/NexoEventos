data "aws_vpc" "source" {
  filter {
    name   = "tag:Name"
    values = ["${var.source_prefix}-vpc"]
  }
}

data "aws_subnet" "public" {
  filter {
    name   = "tag:Name"
    values = ["${var.source_prefix}-public-a"]
  }
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.source.id]
  }
}

data "aws_db_subnet_group" "source" {
  name = "${var.source_prefix}-db-subnets"
}

data "aws_iam_instance_profile" "recovery" {
  name = var.instance_profile_name
}

resource "aws_security_group" "app" {
  name        = "${local.recovery_prefix}-app-sg"
  description = "Aplicacion temporal del ensayo de recuperacion"
  vpc_id      = data.aws_vpc.source.id
  tags        = { Name = "${local.recovery_prefix}-app-sg" }
}

resource "aws_vpc_security_group_ingress_rule" "http" {
  security_group_id = aws_security_group.app.id
  description       = "ACME y redireccion HTTPS del dominio temporal"
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_vpc_security_group_ingress_rule" "https" {
  security_group_id = aws_security_group.app.id
  description       = "HTTPS publico del dominio temporal"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_vpc_security_group_egress_rule" "https" {
  security_group_id = aws_security_group.app.id
  description       = "Servicios AWS, paquetes, DNS dinamico y ACME"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_vpc_security_group_egress_rule" "dns_udp" {
  security_group_id = aws_security_group.app.id
  description       = "DNS de la VPC"
  ip_protocol       = "udp"
  from_port         = 53
  to_port           = 53
  cidr_ipv4         = data.aws_vpc.source.cidr_block
}

resource "aws_vpc_security_group_egress_rule" "dns_tcp" {
  security_group_id = aws_security_group.app.id
  description       = "DNS TCP de la VPC"
  ip_protocol       = "tcp"
  from_port         = 53
  to_port           = 53
  cidr_ipv4         = data.aws_vpc.source.cidr_block
}

resource "aws_security_group" "database" {
  name        = "${local.recovery_prefix}-db-sg"
  description = "RDS temporal solo desde la aplicacion temporal"
  vpc_id      = data.aws_vpc.source.id
  tags        = { Name = "${local.recovery_prefix}-db-sg" }
}

resource "aws_vpc_security_group_ingress_rule" "postgres" {
  security_group_id            = aws_security_group.database.id
  description                  = "PostgreSQL solo desde el SG de recuperacion"
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
  referenced_security_group_id = aws_security_group.app.id
}

resource "aws_vpc_security_group_egress_rule" "postgres" {
  security_group_id            = aws_security_group.app.id
  description                  = "Aplicacion temporal hacia RDS temporal"
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
  referenced_security_group_id = aws_security_group.database.id
}

# Cifrado: la restauración hereda el de la RDS de origen (storage_encrypted = true en infra/aws/database.tf); se declara explícito (AWS-0080).
resource "aws_db_instance" "recovery" {
  identifier                   = "${local.recovery_prefix}-postgres"
  instance_class               = var.db_instance_class
  storage_type                 = "gp2"
  storage_encrypted            = true
  db_subnet_group_name         = data.aws_db_subnet_group.source.name
  vpc_security_group_ids       = [aws_security_group.database.id]
  publicly_accessible          = false
  multi_az                     = false
  backup_retention_period      = 0
  copy_tags_to_snapshot        = false
  deletion_protection          = false
  skip_final_snapshot          = true
  delete_automated_backups     = true
  auto_minor_version_upgrade   = false
  monitoring_interval          = 0
  performance_insights_enabled = false
  apply_immediately            = true

  restore_to_point_in_time {
    source_db_instance_identifier = "${var.source_prefix}-postgres"
    use_latest_restorable_time    = true
  }

  timeouts {
    create = "60m"
    delete = "40m"
  }

  tags = { Name = "${local.recovery_prefix}-postgres" }
}

resource "aws_instance" "app" {
  ami                         = var.ec2_ami_id
  instance_type               = var.ec2_instance_type
  subnet_id                   = data.aws_subnet.public.id
  vpc_security_group_ids      = [aws_security_group.app.id]
  associate_public_ip_address = true
  iam_instance_profile        = data.aws_iam_instance_profile.recovery.name
  monitoring                  = false
  metadata_options {
    http_endpoint = "enabled"
    http_tokens   = "required"
  }
  root_block_device {
    volume_type           = "gp3"
    volume_size           = 20
    encrypted             = true
    delete_on_termination = true
  }
  tags = { Name = "${local.recovery_prefix}-app" }
}
