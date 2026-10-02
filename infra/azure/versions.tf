terraform {
  required_version = ">= 1.16.0, < 2.0.0"
}

variable "azure_region" {
  description = "Región por confirmar contra políticas y cuota antes del despliegue."
  type        = string
  default     = "eastus"
}

locals {
  project_name = "nexoeventos"
}
