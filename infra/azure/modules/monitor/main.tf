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
variable "subscription_id" { type = string }
variable "alert_emails" { type = list(string) }
variable "vm_id" { type = string }
variable "create_vm_alerts" { type = bool }
variable "enable_activity_log" { type = bool }

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

# Registro de actividad de la suscripción (quién crea/modifica qué) hacia Log Analytics: evidencia de auditoría. Volumen mínimo; el tope diario del espacio de trabajo protege el crédito.
resource "azurerm_monitor_diagnostic_setting" "activity" {
  count                      = var.enable_activity_log ? 1 : 0
  name                       = "actividad-suscripcion"
  target_resource_id         = "/subscriptions/${var.subscription_id}"
  log_analytics_workspace_id = azurerm_log_analytics_workspace.this.id

  enabled_log { category = "Administrative" }
  enabled_log { category = "Security" }
  enabled_log { category = "Alert" }
  enabled_log { category = "Policy" }
}

# Grupo de acción: aviso por correo de las alertas de Azure Monitor (sin secretos: solo direcciones). Sin correos no se crea.
resource "azurerm_monitor_action_group" "ops" {
  count               = length(var.alert_emails) > 0 ? 1 : 0
  name                = "ag-nexoeventos-obs"
  resource_group_name = var.resource_group_name
  short_name          = "nexoobs"
  tags                = var.tags

  dynamic "email_receiver" {
    for_each = { for i, e in var.alert_emails : tostring(i) => e }
    content {
      name                    = "operador-${email_receiver.key}"
      email_address           = email_receiver.value
      use_common_alert_schema = true
    }
  }
}

# Alertas de métricas de plataforma de la VM de monitoreo (sin agente ni costo de ingesta). Solo existen mientras la VM exista.
locals {
  vm_alerts = var.create_vm_alerts && length(var.alert_emails) > 0 ? {
    cpu = { metric = "Percentage CPU", operator = "GreaterThan", threshold = 80, severity = 2, window = "PT15M", freq = "PT5M", desc = "CPU de la VM de monitoreo > 80 % durante 15 min" }
    mem = { metric = "Available Memory Bytes", operator = "LessThan", threshold = 419430400, severity = 2, window = "PT15M", freq = "PT5M", desc = "Memoria disponible < 400 MiB durante 15 min" }
    up  = { metric = "VmAvailabilityMetric", operator = "LessThan", threshold = 1, severity = 1, window = "PT5M", freq = "PT1M", desc = "La VM de monitoreo no está disponible" }
  } : {}
}

resource "azurerm_monitor_metric_alert" "vm" {
  for_each            = local.vm_alerts
  name                = "alerta-vm-${each.key}"
  resource_group_name = var.resource_group_name
  scopes              = [var.vm_id]
  description         = each.value.desc
  severity            = each.value.severity
  frequency           = each.value.freq
  window_size         = each.value.window
  auto_mitigate       = true
  tags                = var.tags

  criteria {
    metric_namespace = "Microsoft.Compute/virtualMachines"
    metric_name      = each.value.metric
    aggregation      = each.key == "up" ? "Average" : (each.key == "mem" ? "Minimum" : "Average")
    operator         = each.value.operator
    threshold        = each.value.threshold
  }

  action {
    action_group_id = azurerm_monitor_action_group.ops[0].id
  }
}

output "workspace_id" { value = azurerm_log_analytics_workspace.this.id }
output "action_group_id" { value = length(azurerm_monitor_action_group.ops) > 0 ? azurerm_monitor_action_group.ops[0].id : null }
