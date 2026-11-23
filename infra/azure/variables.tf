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
    condition     = var.admin_cidr == "" || (can(cidrhost(var.admin_cidr, 0)) && var.admin_cidr != "0.0.0.0/0" && endswith(var.admin_cidr, "/32"))
    error_message = "admin_cidr debe ser una única IP /32 y nunca 0.0.0.0/0."
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
  description = "Standard_B2s (y toda la serie B) está restringida («NotAvailableForSubscription») para Azure for Students (comprobado el 28-oct-2026). Se usa Standard_D2s_v4 (2 vCPU / 8 GiB, Gen2/Trusted Launch), la más barata disponible con cuota en centralus (≈ USD 0,108/h). Solo se admite este tamaño."
  type        = string
  default     = "Standard_D2s_v4"
  validation {
    condition     = var.vm_size == "Standard_D2s_v4"
    error_message = "Tamaño autorizado: Standard_D2s_v4. Cualquier otro requiere una decisión explícita (costo y cuota)."
  }
}

variable "ssh_public_key" {
  description = "Clave PÚBLICA SSH del operador."
  type        = string
  default     = ""
}

variable "budget_amount_usd" {
  description = "Presupuesto mensual de la suscripción; alertas al 50/80/100 % real y 100 % previsto. Saldo de crédito verificado el 27-oct-2026: USD 100,00 (consulta de solo lectura); se fija 60 como tope operativo."
  type        = number
  default     = 60
}

variable "budget_start_date" {
  description = "Primer día de un mes (AAAA-MM-01T00:00:00Z)."
  type        = string
  default     = "2026-10-01T00:00:00Z"
}

variable "alert_emails" {
  description = "Correos para el presupuesto y el grupo de acción de Azure Monitor (tfvars local; no van en Git)."
  type        = list(string)
  default     = []
}

variable "dns_label" {
  description = "Etiqueta DNS gratuita de la IP pública (<etiqueta>.<región>.cloudapp.azure.com), en minúsculas. Vacío = sin nombre."
  type        = string
  default     = ""
  validation {
    condition     = var.dns_label == "" || can(regex("^[a-z][a-z0-9-]{2,60}[a-z0-9]$", var.dns_label))
    error_message = "dns_label: minúsculas, números y guiones (3–62)."
  }
}

variable "enable_activity_log" {
  description = "Envía el registro de actividad de la suscripción a Log Analytics (auditoría; volumen mínimo)."
  type        = bool
  default     = true
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

variable "enable_auto_shutdown" {
  description = "Apagado automático (DevTest Labs, Microsoft.DevTestLab/schedules): DESASIGNA la VM todos los días a shutdown_time_utc. Obligatorio mientras exista la VM."
  type        = bool
  default     = true
}

variable "shutdown_time_utc" {
  description = "Hora UTC (HHmm, 24 h) del apagado diario. Se fija con scripts/observability/azure-set-shutdown-window.sh = ahora + duración de la ventana. Sin valor, el plan con VM se rechaza."
  type        = string
  default     = ""
  validation {
    condition     = var.shutdown_time_utc == "" || can(regex("^([01][0-9]|2[0-3])[0-5][0-9]$", var.shutdown_time_utc))
    error_message = "shutdown_time_utc debe ser HHmm en 24 h (por ejemplo 1830)."
  }
}

