variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "expected_account_id" {
  type      = string
  sensitive = true
  validation {
    condition     = can(regex("^[0-9]{12}$", var.expected_account_id))
    error_message = "expected_account_id debe contener 12 dígitos."
  }
}

variable "source_prefix" {
  type    = string
  default = "nexoeventos-academy"
  validation {
    condition     = var.source_prefix == "nexoeventos-academy"
    error_message = "Este ensayo está limitado al entorno Academy comprobado."
  }
}

variable "run_id" {
  description = "Identificador UTC del ensayo, por ejemplo 20261020t1400."
  type        = string
  validation {
    condition     = can(regex("^[0-9]{8}t[0-9]{4}$", var.run_id))
    error_message = "run_id debe usar AAAAMMDDtHHMM."
  }
}

variable "ec2_ami_id" {
  description = "La misma AMI AL2023 fijada y comprobada en V1."
  type        = string
  validation {
    condition     = can(regex("^ami-[0-9a-f]{8,17}$", var.ec2_ami_id))
    error_message = "ec2_ami_id debe ser una AMI explícita."
  }
}

variable "instance_profile_name" {
  type = string
  validation {
    condition     = length(trimspace(var.instance_profile_name)) > 0
    error_message = "Se requiere un perfil IAM existente; Terraform no amplía IAM."
  }
}

variable "ec2_instance_type" {
  type    = string
  default = "t3.small"
  validation {
    condition     = var.ec2_instance_type == "t3.small"
    error_message = "El ensayo aprobado debe conservar t3.small; otro tamaño exige recalcular y aprobar costo."
  }
}

variable "db_instance_class" {
  type    = string
  default = "db.t3.micro"
  validation {
    condition     = var.db_instance_class == "db.t3.micro"
    error_message = "El ensayo aprobado debe conservar db.t3.micro; otra clase exige recalcular y aprobar costo."
  }
}

locals {
  recovery_prefix = "${var.source_prefix}-recovery-${var.run_id}"
  common_tags = {
    Project     = "NexoEventos"
    Environment = "recovery"
    Purpose     = "full-recovery-drill"
    RunId       = var.run_id
    ManagedBy   = "Terraform"
    Academic    = "true"
  }
}
