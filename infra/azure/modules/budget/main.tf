variable "subscription_id" { type = string }
variable "amount_usd" { type = number }
variable "start_date" { type = string }
variable "alert_emails" { type = list(string) }
variable "resource_group_id" { type = string }

# Presupuesto con alertas al 50/80/100 % del importe (real) y 100 % previsto. Solo avisa; no detiene recursos.
resource "azurerm_consumption_budget_subscription" "this" {
  name            = "presupuesto-nexoeventos"
  subscription_id = "/subscriptions/${var.subscription_id}"
  amount          = var.amount_usd
  time_grain      = "Monthly"

  lifecycle {
    precondition {
      condition     = length(var.alert_emails) > 0
      error_message = "El presupuesto necesita al menos un correo de contacto (alert_emails)."
    }
  }

  time_period {
    start_date = var.start_date
  }

  dynamic "notification" {
    for_each = [50, 80, 100]
    content {
      enabled        = true
      threshold      = notification.value
      operator       = "GreaterThan"
      threshold_type = "Actual"
      contact_emails = var.alert_emails
    }
  }

  notification {
    enabled        = true
    threshold      = 100
    operator       = "GreaterThan"
    threshold_type = "Forecasted"
    contact_emails = var.alert_emails
  }
}
