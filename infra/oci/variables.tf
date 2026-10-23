variable "region" {
  description = "Región de ORIGEN de la tenencia (los recursos Always Free solo valen allí). Se confirma al crear la cuenta."
  type        = string
  validation {
    condition     = can(regex("^[a-z]{2}-[a-z]+-[0-9]+$", var.region))
    error_message = "region debe tener el formato de una región OCI (p. ej. us-ashburn-1)."
  }
}

variable "config_file_profile" {
  type    = string
  default = "DEFAULT"
}

variable "tenancy_ocid" {
  description = "OCID de la tenencia (no es un secreto, pero tampoco va en Git: tfvars local)."
  type        = string
  validation {
    condition     = can(regex("^ocid1\\.tenancy\\.", var.tenancy_ocid))
    error_message = "tenancy_ocid debe ser un OCID de tenencia."
  }
}

variable "compartment_name" {
  type    = string
  default = "nexoeventos"
}

variable "vcn_cidr" {
  description = "CIDR propuesto; no debe solaparse con AWS 10.20.0.0/16 ni con Azure 10.40.0.0/16 (se comprueba en scripts/multicloud/check-coherence.py)."
  type        = string
  default     = "10.30.0.0/16"
  validation {
    condition     = can(cidrhost(var.vcn_cidr, 0))
    error_message = "vcn_cidr no es un CIDR válido."
  }
}

variable "private_subnet_cidr" {
  type    = string
  default = "10.30.1.0/24"
  validation {
    condition     = can(cidrhost(var.private_subnet_cidr, 0))
    error_message = "private_subnet_cidr no es un CIDR válido."
  }
}

variable "enable_nat_gateway" {
  description = "Solo para instalar PostgreSQL desde Internet en la VM de recuperación. Desactivado: la subred es 100 % privada."
  type        = bool
  default     = false
}

variable "bucket_name" {
  type    = string
  default = "nexoeventos-recovery"
}

variable "uploader_user_name" {
  type        = string
  description = "Usuario de servicio que carga las copias; solo puede usar clave API."
  default     = "nexoeventos-backup-uploader"
}

variable "uploader_user_email" {
  type        = string
  sensitive   = true
  description = "Correo principal del usuario de servicio (el dominio de identidad lo exige). Solo en el tfvars local, nunca en Git."
}

variable "uploader_group_name" {
  description = "Grupo IAM (creado en la consola) con permiso de ESCRITURA/LECTURA solo en este bucket."
  type        = string
  default     = "nexoeventos-backup-uploaders"
}

variable "create_recovery_vm" {
  description = "false por defecto: la VM se crea solo para un simulacro y se destruye después."
  type        = bool
  default     = false
}

variable "recovery_boot_volume_gb" {
  type        = number
  default     = 50
  description = "Volumen de arranque (Always Free: 200 GB de bloque en total). Mínimo de la imagen: 47 GB."
  validation {
    condition     = var.recovery_boot_volume_gb >= 47 && var.recovery_boot_volume_gb <= 100
    error_message = "recovery_boot_volume_gb debe estar entre 47 y 100."
  }
}

variable "recovery_flex_ocpus" {
  type    = number
  default = 1
}

variable "recovery_flex_memory_gb" {
  type    = number
  default = 6
}

variable "recovery_shape" {
  description = "Always Free: VM.Standard.E2.1.Micro (1/8 OCPU, 1 GB). La base es de unos KB; basta para el simulacro."
  type        = string
  default     = "VM.Standard.E2.1.Micro"
}

variable "ssh_public_key" {
  description = "Clave PÚBLICA SSH del operador (no la privada)."
  type        = string
  default     = ""
}

variable "bastion_client_cidr" {
  description = "IP /32 del operador autorizada en OCI Bastion. Vacío = sin Bastion."
  type        = string
  default     = ""
  validation {
    condition     = var.bastion_client_cidr == "" || (can(cidrhost(var.bastion_client_cidr, 0)) && endswith(var.bastion_client_cidr, "/32"))
    error_message = "bastion_client_cidr debe ser un único /32 (la IP del operador) o vacío."
  }
}

locals {
  common_tags = { Project = "NexoEventos", Role = "recuperacion", ManagedBy = "Terraform" }
}
