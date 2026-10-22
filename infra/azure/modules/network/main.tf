variable "location" { type = string }
variable "vnet_cidr" { type = string }
variable "subnet_cidr" { type = string }
variable "admin_cidr" { type = string }
variable "zabbix_agent_source_cidrs" { type = list(string) }
variable "tags" { type = map(string) }

resource "azurerm_resource_group" "this" {
  name     = "rg-nexoeventos-observabilidad"
  location = var.location
  tags     = var.tags
}

resource "azurerm_virtual_network" "this" {
  name                = "vnet-nexoeventos-obs"
  resource_group_name = azurerm_resource_group.this.name
  location            = var.location
  address_space       = [var.vnet_cidr]
  tags                = var.tags
}

resource "azurerm_subnet" "monitoring" {
  name                 = "snet-monitoring"
  resource_group_name  = azurerm_resource_group.this.name
  virtual_network_name = azurerm_virtual_network.this.name
  address_prefixes     = [var.subnet_cidr]
}

# NSG: sin reglas abiertas a Internet. SSH y HTTPS (Nginx → Grafana/Zabbix) solo desde la IP del operador; 10051 solo desde las IPs de AWS indicadas (Fase B).
resource "azurerm_network_security_group" "monitoring" {
  name                = "nsg-nexoeventos-obs"
  resource_group_name = azurerm_resource_group.this.name
  location            = var.location
  tags                = var.tags

  dynamic "security_rule" {
    for_each = var.admin_cidr == "" ? [] : [22, 443]
    content {
      name                       = "admin-${security_rule.value}"
      priority                   = 100 + security_rule.value % 100
      direction                  = "Inbound"
      access                     = "Allow"
      protocol                   = "Tcp"
      source_port_range          = "*"
      destination_port_range     = tostring(security_rule.value)
      source_address_prefix      = var.admin_cidr
      destination_address_prefix = "*"
    }
  }

  dynamic "security_rule" {
    for_each = length(var.zabbix_agent_source_cidrs) == 0 ? [] : [1]
    content {
      name                       = "zabbix-trapper"
      priority                   = 300
      direction                  = "Inbound"
      access                     = "Allow"
      protocol                   = "Tcp"
      source_port_range          = "*"
      destination_port_range     = "10051"
      source_address_prefixes    = var.zabbix_agent_source_cidrs
      destination_address_prefix = "*"
    }
  }
}

resource "azurerm_subnet_network_security_group_association" "monitoring" {
  subnet_id                 = azurerm_subnet.monitoring.id
  network_security_group_id = azurerm_network_security_group.monitoring.id
}

output "resource_group_name" { value = azurerm_resource_group.this.name }
output "resource_group_id" { value = azurerm_resource_group.this.id }
output "subnet_id" { value = azurerm_subnet.monitoring.id }
