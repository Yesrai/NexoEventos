variable "resource_group_name" { type = string }
variable "location" { type = string }
variable "enable_tests" { type = bool }
variable "urls" {
  type = list(string)
  validation {
    condition     = alltrue([for u in var.urls : startswith(u, "https://")])
    error_message = "Solo se comprueban URLs HTTPS."
  }
}
variable "tags" { type = map(string) }

# Log Analytics: 30 días de retención y tope diario bajo para no consumir el crédito (ingesta gratuita: primeros 5 GB/mes; verificar).
resource "azurerm_log_analytics_workspace" "this" {
  name                = "log-nexoeventos-obs"
  resource_group_name = var.resource_group_name
  location            = var.location
  sku                 = "PerGB2018"
  retention_in_days   = 30
  daily_quota_gb      = 0.2
  tags                = var.tags
}

# Pruebas de disponibilidad HTTPS externas: desactivadas por defecto hasta verificar su costo.
resource "azurerm_application_insights" "this" {
  count               = var.enable_tests ? 1 : 0
  name                = "appi-nexoeventos-obs"
  resource_group_name = var.resource_group_name
  location            = var.location
  workspace_id        = azurerm_log_analytics_workspace.this.id
  application_type    = "web"
  tags                = var.tags
}

resource "azurerm_application_insights_standard_web_test" "https" {
  for_each                = var.enable_tests ? { for i, u in var.urls : tostring(i) => u } : {}
  name                    = "https-check-${each.key}"
  resource_group_name     = var.resource_group_name
  location                = var.location
  application_insights_id = azurerm_application_insights.this[0].id
  geo_locations           = ["us-tx-sn1-azr", "us-il-ch1-azr", "us-va-ash-azr"]
  frequency               = 300
  timeout                 = 30
  enabled                 = true
  tags                    = var.tags

  request {
    url = each.value
  }

  validation_rules {
    expected_status_code        = 200
    ssl_check_enabled           = true
    ssl_cert_remaining_lifetime = 14
  }
}

output "workspace_id" { value = azurerm_log_analytics_workspace.this.id }
