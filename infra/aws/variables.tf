variable "aws_region" {
  description = "Región elegida para este entorno. Debe validarse contra permisos, cuotas y costos de la cuenta."
  type        = string
  default     = "us-east-1"
  validation {
    condition     = can(regex("^[a-z]{2}(-gov)?-[a-z]+-[0-9]+$", var.aws_region))
    error_message = "aws_region debe tener el formato de una región AWS."
  }
}

variable "expected_account_id" {
  description = "ID de 12 dígitos de la cuenta autorizada. Se mantiene en un tfvars local ignorado por Git."
  type        = string
  sensitive   = true
  validation {
    condition     = can(regex("^[0-9]{12}$", var.expected_account_id))
    error_message = "expected_account_id debe contener exactamente 12 dígitos."
  }
}

variable "project_slug" {
  type    = string
  default = "nexoeventos"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,30}$", var.project_slug))
    error_message = "project_slug debe empezar por letra y usar minúsculas, números o guiones."
  }
}

variable "environment" {
  type    = string
  default = "demo"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,20}$", var.environment))
    error_message = "environment debe empezar por letra y usar minúsculas, números o guiones."
  }
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

variable "ec2_ami_id" {
  description = "AMI exacta de Amazon Linux 2023 desplegada en este entorno. Se fija por cuenta para evitar reemplazos por most_recent."
  type        = string
  validation {
    condition     = can(regex("^ami-[0-9a-f]{8,17}$", var.ec2_ami_id))
    error_message = "ec2_ami_id debe ser un identificador AMI válido y explícito."
  }
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
  description = "Perfil IAM ya existente y autorizado. Academy suele usar LabInstanceProfile; otras cuentas requieren uno propio."
  type        = string
  validation {
    condition     = length(trimspace(var.instance_profile_name)) > 0
    error_message = "instance_profile_name es obligatorio para cada cuenta."
  }
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

variable "db_max_allocated_storage_gib" {
  description = "0 o igual a allocated_storage desactiva el autoescalado (el estado actual de la RDS usa el valor igual). Si se habilita, AWS exige al menos 10 % sobre allocated_storage; Academy limita el techo a 100 GiB."
  type        = number
  default     = 0
  validation {
    condition = (
      var.db_max_allocated_storage_gib == 0 ||
      var.db_max_allocated_storage_gib == var.db_allocated_storage_gib ||
      (var.db_max_allocated_storage_gib >= ceil(var.db_allocated_storage_gib * 1.1) &&
      var.db_max_allocated_storage_gib <= 100)
    )
    error_message = "db_max_allocated_storage_gib debe ser 0, igual al almacenamiento asignado o al menos 10 % mayor que el almacenamiento asignado, hasta 100 GiB."
  }
}

variable "db_multi_az" {
  type        = bool
  default     = false
  description = "Alta disponibilidad de PostgreSQL con réplica síncrona en otra AZ. Duplica el costo de instancia y almacenamiento."
}

variable "db_apply_immediately" {
  type        = bool
  default     = false
  description = "Aplicar cambios de RDS ya, en vez de en la ventana de mantenimiento."
}

variable "backup_retention_days" {
  description = "Retención de las copias automáticas de RDS (días). NO controla la caducidad de los respaldos cifrados en S3 (ver s3_backup_retention_days)."
  type        = number
  default     = 7
}

variable "s3_backup_retention_days" {
  description = "Días que se conservan en S3 los respaldos cifrados de `backups/database/` y sus versiones no vigentes. Antes se reutilizaba backup_retention_days (7): alinear el prefijo del lifecycle con ese valor habría borrado los respaldos reales. Mínimo 30. Por defecto 365: los respaldos pesan KB (coste ≈ 0), así que caducarlos pronto solo añade riesgo de perder la única copia restaurable; subir/bajar solo con decisión expresa."
  type        = number
  default     = 365
  validation {
    condition     = var.s3_backup_retention_days >= 30 && var.s3_backup_retention_days <= 3650
    error_message = "s3_backup_retention_days debe estar entre 30 y 3650 días."
  }
}
variable "log_retention_days" {
  type    = number
  default = 7
}

variable "final_snapshot_identifier" {
  description = "Nombre único del snapshot final. Debe cambiarse antes de una eliminación posterior si ya existe."
  type        = string
  validation {
    condition = (
      length(var.final_snapshot_identifier) >= 1 &&
      length(var.final_snapshot_identifier) <= 255 &&
      can(regex("^[A-Za-z][A-Za-z0-9-]*[A-Za-z0-9]$", var.final_snapshot_identifier)) &&
      !strcontains(var.final_snapshot_identifier, "--")
    )
    error_message = "El snapshot debe empezar por letra, terminar en letra/número y no contener guiones consecutivos."
  }
}

locals {
  project_name = var.project_slug
  name_prefix  = "${var.project_slug}-${var.environment}"
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

variable "public_subnet_auto_public_ip" {
  description = "Asigna IP pública automática a lo que se lance en la subred pública de V1 (AWS-0164). false (recomendado y por defecto): la EC2 ya la pide explícitamente. Solo existe para poder aplicar otros cambios (p. ej. alarmas) SIN tocar la subred: con un apply dirigido a una EC2 la subred entra como dependencia; pasar true mantiene el valor desplegado hasta decidir el cambio de red por separado."
  type        = bool
  default     = false
}
