# Segunda subred pública (otra zona de disponibilidad) y su asociación a la tabla de rutas pública de V1 (hacia el IGW existente).
resource "aws_subnet" "public_b" {
  vpc_id                  = data.aws_vpc.v1.id
  cidr_block              = var.public_b_cidr
  availability_zone       = data.aws_availability_zones.available.names[1]
  map_public_ip_on_launch = false # la IP pública se pide por instancia (AWS-0164)
  tags                    = { Name = "${local.v2_prefix}-public-b", Tier = "public" }

  lifecycle {
    precondition {
      condition     = data.aws_subnet.public_a.availability_zone != data.aws_availability_zones.available.names[1]
      error_message = "La subred pública de V1 ya está en la segunda zona; elija otra para V2."
    }
  }
}

resource "aws_route_table_association" "public_b" {
  subnet_id      = aws_subnet.public_b.id
  route_table_id = data.aws_route_table.public.id
}

# --- Grupos de seguridad ---------------------------------------------------------------------------------------------------
# Las instancias NO aceptan tráfico de Internet: el único origen permitido en el puerto 80 es el grupo de seguridad del ALB.

resource "aws_security_group" "alb" {
  name        = "${local.v2_prefix}-alb-sg"
  description = "ALB de NexoEventos V2: HTTPS y HTTP (redireccion) publicos"
  vpc_id      = data.aws_vpc.v1.id
  tags        = { Name = "${local.v2_prefix}-alb-sg" }
}

resource "aws_vpc_security_group_ingress_rule" "alb_https" {
  security_group_id = aws_security_group.alb.id
  description       = "HTTPS publico"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_vpc_security_group_ingress_rule" "alb_http" {
  security_group_id = aws_security_group.alb.id
  description       = "HTTP solo para redirigir a HTTPS"
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_security_group" "web" {
  name        = "${local.v2_prefix}-web-sg"
  description = "Instancias de NexoEventos V2: solo trafico desde el ALB"
  vpc_id      = data.aws_vpc.v1.id
  tags        = { Name = "${local.v2_prefix}-web-sg" }
}

resource "aws_vpc_security_group_ingress_rule" "web_from_alb" {
  security_group_id            = aws_security_group.web.id
  description                  = "HTTP desde el ALB unicamente"
  ip_protocol                  = "tcp"
  from_port                    = 80
  to_port                      = 80
  referenced_security_group_id = aws_security_group.alb.id
}

resource "aws_vpc_security_group_egress_rule" "alb_to_web" {
  security_group_id            = aws_security_group.alb.id
  description                  = "Hacia las instancias por HTTP"
  ip_protocol                  = "tcp"
  from_port                    = 80
  to_port                      = 80
  referenced_security_group_id = aws_security_group.web.id
}

resource "aws_vpc_security_group_egress_rule" "web_https" {
  security_group_id = aws_security_group.web.id
  description       = "Servicios AWS (Session Manager, S3, Secrets Manager, CloudWatch) y paquetes por HTTPS"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_vpc_security_group_egress_rule" "web_dns_udp" {
  security_group_id = aws_security_group.web.id
  description       = "DNS dentro de la VPC"
  ip_protocol       = "udp"
  from_port         = 53
  to_port           = 53
  cidr_ipv4         = data.aws_vpc.v1.cidr_block
}

resource "aws_vpc_security_group_egress_rule" "web_dns_tcp" {
  security_group_id = aws_security_group.web.id
  description       = "DNS TCP dentro de la VPC"
  ip_protocol       = "tcp"
  from_port         = 53
  to_port           = 53
  cidr_ipv4         = data.aws_vpc.v1.cidr_block
}

resource "aws_vpc_security_group_egress_rule" "web_postgres" {
  security_group_id            = aws_security_group.web.id
  description                  = "PostgreSQL hacia la RDS"
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
  referenced_security_group_id = data.aws_security_group.database.id
}

# Regla ADITIVA sobre el SG de la base de V1: permite 5432 desde el SG de V2 (V1 conserva la suya; no se modifica su estado).
resource "aws_vpc_security_group_ingress_rule" "postgres_from_web_v2" {
  security_group_id            = data.aws_security_group.database.id
  description                  = "PostgreSQL desde las instancias de V2"
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
  referenced_security_group_id = aws_security_group.web.id
}
