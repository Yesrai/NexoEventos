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
  tags                = local.common_tags
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
  tags                = local.common_tags
}
