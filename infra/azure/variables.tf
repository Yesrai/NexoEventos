variable "subscription_id" {
  description = "ID de la suscripción Azure for Students (tfvars local; no va en Git)."
  type        = string
  validation {
    condition     = can(regex("^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", var.subscription_id))
    error_message = "subscription_id debe ser un GUID."
  }
}

variable "azure_region" {
  description = "Solo regiones permitidas por la directiva de la suscripción (diagnóstico 22-oct-2026)."
  type        = string
  default     = "centralus"
  validation {
    condition     = contains(["southcentralus", "mexicocentral", "westus3", "canadacentral", "centralus"], var.azure_region)
    error_message = "La directiva Allowed resource deployment regions deniega otras regiones."
  }
}

variable "vnet_cidr" {
  description = "CIDR propuesto; sin solape con AWS 10.20.0.0/16 ni OCI 10.30.0.0/16 (scripts/multicloud/check-coherence.py)."
  type        = string
  default     = "10.40.0.0/16"
  validation {
    condition     = can(cidrhost(var.vnet_cidr, 0))
    error_message = "vnet_cidr no es un CIDR válido."
  }
}

variable "subnet_cidr" {
  type    = string
  default = "10.40.1.0/24"
  validation {
    condition     = can(cidrhost(var.subnet_cidr, 0))
    error_message = "subnet_cidr no es un CIDR válido."
  }
}

variable "admin_cidr" {
  description = "IP /32 del operador para SSH y HTTPS de Zabbix/Grafana. Obligatoria si se crea la VM."
  type        = string
  default     = ""
  validation {
    condition     = var.admin_cidr == "" || (can(cidrhost(var.admin_cidr, 0)) && var.admin_cidr != "0.0.0.0/0")
    error_message = "admin_cidr debe ser un CIDR concreto y nunca 0.0.0.0/0."
  }
}

variable "zabbix_agent_source_cidrs" {
  description = "IPs de salida de AWS autorizadas a enviar a Zabbix (puerto 10051). Vacío = sin regla (Fase A: solo comprobaciones HTTP)."
  type        = list(string)
  default     = []
}

variable "create_monitoring_vm" {
  description = "false por defecto: la VM (y su IP) solo existe durante las ventanas de monitoreo."
  type        = bool
  default     = false
}

variable "vm_size" {
  description = "2 vCPU / 4 GB suficiente para Zabbix + PostgreSQL + Grafana. Validar disponibilidad y cuota en la región antes de crear."
  type        = string
  default     = "Standard_B2s"
}

variable "ssh_public_key" {
  description = "Clave PÚBLICA SSH del operador."
  type        = string
  default     = ""
}

variable "budget_amount_usd" {
  description = "Presupuesto mensual del grupo de recursos; la alerta se dispara al 50/80/100 %. Crédito inicial informado: 100 (sin verificar)."
  type        = number
  default     = 100
}

variable "budget_start_date" {
  description = "Primer día de un mes (AAAA-MM-01T00:00:00Z)."
  type        = string
  default     = "2026-11-01T00:00:00Z"
}

variable "alert_emails" {
  type    = list(string)
  default = []
}

variable "enable_availability_tests" {
  description = "Pruebas de disponibilidad HTTPS externas (Application Insights). Verificar su costo antes de activarlas."
  type        = bool
  default     = false
}

variable "monitored_urls" {
  description = "URLs HTTPS a comprobar (p. ej. el ALB de V2 o V1 cuando estén activos)."
  type        = list(string)
  default     = []
}

locals {
  common_tags = { project = "NexoEventos", role = "observabilidad", managed_by = "Terraform" }
}
