module "network" {
  source                    = "./modules/network"
  location                  = var.azure_region
  vnet_cidr                 = var.vnet_cidr
  subnet_cidr               = var.subnet_cidr
  admin_cidr                = var.admin_cidr
  zabbix_agent_source_cidrs = var.zabbix_agent_source_cidrs
  tags                      = local.common_tags
}

module "vm" {
  source              = "./modules/vm"
  create              = var.create_monitoring_vm
  resource_group_name = module.network.resource_group_name
  location            = var.azure_region
  subnet_id           = module.network.subnet_id
  vm_size             = var.vm_size
  ssh_public_key      = var.ssh_public_key
  admin_cidr          = var.admin_cidr
  dns_label           = var.dns_label
  tags                = local.common_tags
}

# La identidad administrada de la VM solo puede LEER métricas de Azure Monitor del grupo de recursos (Grafana → Azure Monitor sin secretos).
resource "azurerm_role_assignment" "grafana_monitoring_reader" {
  count                            = var.create_monitoring_vm ? 1 : 0
  scope                            = module.network.resource_group_id
  role_definition_name             = "Monitoring Reader"
  principal_id                     = module.vm.principal_id
  skip_service_principal_aad_check = true
}

# Apagado automático de seguridad (independiente de la estación del operador). El servicio solo admite UNA hora fija DIARIA: la hora se calcula al desplegar
# (ahora + ventana); si la VM se vuelve a encender otro día, se desasignará a esa misma hora. Zona UTC para evitar el horario de verano. Sin notificaciones
# (no hay correo ni webhook en el plan). No necesita un laboratorio de DevTest Labs: es un recurso suelto en el grupo de recursos. Gratuito.
resource "azurerm_dev_test_global_vm_shutdown_schedule" "vm" {
  count                 = var.create_monitoring_vm && var.enable_auto_shutdown ? 1 : 0
  virtual_machine_id    = module.vm.vm_id
  location              = var.azure_region
  enabled               = true
  daily_recurrence_time = var.shutdown_time_utc
  timezone              = "UTC"
  tags                  = local.common_tags

  notification_settings {
    enabled = false
  }

  lifecycle {
    precondition {
      condition     = var.shutdown_time_utc != ""
      error_message = "Defina shutdown_time_utc (HHmm UTC) con scripts/observability/azure-set-shutdown-window.sh antes de planificar la VM."
    }
  }
}

module "budget" {
  source            = "./modules/budget"
  subscription_id   = var.subscription_id
  amount_usd        = var.budget_amount_usd
  start_date        = var.budget_start_date
  alert_emails      = var.alert_emails
  resource_group_id = module.network.resource_group_id
}

module "monitor" {
  source              = "./modules/monitor"
  resource_group_name = module.network.resource_group_name
  location            = var.azure_region
  enable_tests        = var.enable_availability_tests
  urls                = var.monitored_urls
  subscription_id     = var.subscription_id
  alert_emails        = var.alert_emails
  vm_id               = module.vm.vm_id
  create_vm_alerts    = var.create_monitoring_vm
  enable_activity_log = var.enable_activity_log
  tags                = local.common_tags
}
