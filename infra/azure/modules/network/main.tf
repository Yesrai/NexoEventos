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

# NSG de mínimo privilegio.
#   Entrada: SSH (22) y HTTPS (443: Nginx → Grafana/Zabbix, también la API de Zabbix para cargar series históricas) SOLO desde admin_cidr (/32); 10051 solo si se autorizan IPs de AWS
#            (Fase B, agentes activos). Regla explícita de denegación del resto.
#   Salida: solo 443/80 (sondas, repositorios y paquetes), DNS (53) y NTP (123) hacia Internet, y el servicio de plataforma de Azure (168.63.129.16). Se deniega el resto hacia Internet.
resource "azurerm_network_security_group" "monitoring" {
  name                = "nsg-nexoeventos-obs"
  resource_group_name = azurerm_resource_group.this.name
  location            = var.location
  tags                = var.tags

  dynamic "security_rule" {
    for_each = var.admin_cidr == "" ? {} : { "ssh" = 22, "https" = 443 }
    content {
      name                       = "admin-${security_rule.key}"
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
      name                       = "zabbix-agentes-activos"
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

  security_rule {
    name                       = "deny-all-inbound"
    priority                   = 4096
    direction                  = "Inbound"
    access                     = "Deny"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }

  security_rule {
    name                       = "allow-azure-platform-out"
    priority                   = 100
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "*"
    destination_address_prefix = "168.63.129.16/32"
  }
  security_rule {
    name                       = "allow-web-out"
    priority                   = 200
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_ranges    = ["80", "443"]
    source_address_prefix      = "*"
    destination_address_prefix = "Internet"
  }
  security_rule {
    name                       = "allow-dns-ntp-out"
    priority                   = 210
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_ranges    = ["53", "123"]
    source_address_prefix      = "*"
    destination_address_prefix = "Internet"
  }
  security_rule {
    name                       = "deny-internet-out"
    priority                   = 4000
    direction                  = "Outbound"
    access                     = "Deny"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "*"
    destination_address_prefix = "Internet"
  }
}

resource "azurerm_subnet_network_security_group_association" "monitoring" {
  subnet_id                 = azurerm_subnet.monitoring.id
  network_security_group_id = azurerm_network_security_group.monitoring.id
}

output "resource_group_name" { value = azurerm_resource_group.this.name }
output "resource_group_id" { value = azurerm_resource_group.this.id }
output "subnet_id" { value = azurerm_subnet.monitoring.id }
