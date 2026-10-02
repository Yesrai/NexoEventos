variable "aws_region" {
  description = "Región permitida por Learner Lab. No implica permiso para crear recursos."
  type        = string
  default     = "us-east-1"
  validation {
    condition     = contains(["us-east-1", "us-west-2"], var.aws_region)
    error_message = "Learner Lab solo documenta us-east-1 y us-west-2."
  }
}

variable "environment" {
  type    = string
  default = "demo"
}
variable "vpc_cidr" {
  type    = string
  default = "10.20.0.0/16"
}
variable "public_a_cidr" {
  type    = string
  default = "10.20.1.0/24"
}
variable "db_private_a_cidr" {
  type    = string
  default = "10.20.21.0/24"
}
variable "db_private_b_cidr" {
  type    = string
  default = "10.20.22.0/24"
}

variable "admin_cidr" {
  description = "IPv4 administrativa /32. Vacío mantiene SSH cerrado. No guardar una IP personal en Git."
  type        = string
  default     = ""
  validation {
    condition     = var.admin_cidr == "" || can(cidrhost(var.admin_cidr, 0))
    error_message = "admin_cidr debe estar vacío o ser un CIDR válido."
  }
}

variable "ec2_instance_type" {
  description = "V1 propuesta: 2 vCPU y 2 GiB; confirmar con un plan autenticado."
  type        = string
  default     = "t3.small"
}

variable "ec2_root_volume_gib" {
  type    = number
  default = 20
  validation {
    condition     = var.ec2_root_volume_gib >= 8 && var.ec2_root_volume_gib <= 100
    error_message = "El volumen debe respetar el máximo de 100 GiB del laboratorio."
  }
}

variable "instance_profile_name" {
  type    = string
  default = "LabInstanceProfile"
}
variable "db_instance_class" {
  type    = string
  default = "db.t3.micro"
}

variable "db_allocated_storage_gib" {
  type    = number
  default = 20
  validation {
    condition     = var.db_allocated_storage_gib >= 20 && var.db_allocated_storage_gib <= 100
    error_message = "RDS debe usar entre 20 y 100 GiB."
  }
}

variable "backup_retention_days" {
  type    = number
  default = 7
}
variable "log_retention_days" {
  type    = number
  default = 7
}

locals {
  project_name = "nexoeventos"
  name_prefix  = "${local.project_name}-${var.environment}"
  common_tags = {
    Project     = "NexoEventos"
    Environment = var.environment
    ManagedBy   = "Terraform"
    Academic    = "true"
  }
  v1_subnet_cidrs = [var.public_a_cidr, var.db_private_a_cidr, var.db_private_b_cidr]
}

check "v1_subnets_are_distinct_24s" {
  assert {
    condition     = length(distinct(local.v1_subnet_cidrs)) == 3 && alltrue([for cidr in local.v1_subnet_cidrs : endswith(cidr, "/24")])
    error_message = "Las tres subredes V1 deben ser /24 distintas."
  }
}
