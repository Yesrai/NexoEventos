variable "create" { type = bool }
variable "resource_group_name" { type = string }
variable "location" { type = string }
variable "subnet_id" { type = string }
variable "vm_size" { type = string }
variable "ssh_public_key" { type = string }
variable "admin_cidr" { type = string }
variable "dns_label" { type = string }
variable "tags" { type = map(string) }

resource "azurerm_public_ip" "this" {
  count               = var.create ? 1 : 0
  name                = "pip-nexoeventos-obs"
  resource_group_name = var.resource_group_name
  location            = var.location
  allocation_method   = "Static"
  sku                 = "Standard"
  domain_name_label   = var.dns_label == "" ? null : var.dns_label # nombre gratuito <etiqueta>.<región>.cloudapp.azure.com para el certificado y las URLs
  tags                = var.tags
}

resource "azurerm_network_interface" "this" {
  count               = var.create ? 1 : 0
  name                = "nic-nexoeventos-obs"
  resource_group_name = var.resource_group_name
  location            = var.location
  tags                = var.tags
  ip_configuration {
    name                          = "ipconfig1"
    subnet_id                     = var.subnet_id
    private_ip_address_allocation = "Dynamic"
    public_ip_address_id          = azurerm_public_ip.this[0].id
  }
}

# VM de monitoreo (Zabbix + Grafana, configurada después con Ansible). Solo clave SSH; sin contraseña; Trusted Launch (arranque seguro + vTPM);
# identidad administrada SOLO para que Grafana lea Azure Monitor (rol «Monitoring Reader» acotado al grupo de recursos); sin extensiones de VM.
resource "azurerm_linux_virtual_machine" "this" {
  count                           = var.create ? 1 : 0
  name                            = "vm-nexoeventos-obs"
  resource_group_name             = var.resource_group_name
  location                        = var.location
  size                            = var.vm_size
  admin_username                  = "nexoadmin"
  disable_password_authentication = true
  network_interface_ids           = [azurerm_network_interface.this[0].id]
  allow_extension_operations      = false
  secure_boot_enabled             = true
  vtpm_enabled                    = true
  tags                            = var.tags
  # Huellas de las claves de host por la consola serie (verificación SSH fuera de banda); ver cloud-init-hostkeys.yaml.
  custom_data = filebase64("${path.module}/cloud-init-hostkeys.yaml")

  # Diagnóstico de arranque GESTIONADO por Azure: no crea una cuenta de almacenamiento ni otro recurso facturable; permite leer el registro de arranque.
  boot_diagnostics {}

  identity {
    type = "SystemAssigned"
  }

  admin_ssh_key {
    username   = "nexoadmin"
    public_key = var.ssh_public_key
  }
  os_disk {
    caching              = "ReadWrite"
    storage_account_type = "StandardSSD_LRS"
    disk_size_gb         = 64
  }
  source_image_reference {
    publisher = "Canonical"
    offer     = "ubuntu-24_04-lts"
    sku       = "server"
    version   = "latest"
  }

  lifecycle {
    precondition {
      condition     = var.ssh_public_key != "" && var.admin_cidr != ""
      error_message = "Para crear la VM se requieren ssh_public_key y admin_cidr (el NSG no abre nada a Internet)."
    }
  }
}

output "public_ip" { value = var.create ? azurerm_public_ip.this[0].ip_address : null }
output "fqdn" { value = var.create ? azurerm_public_ip.this[0].fqdn : null }
output "vm_id" { value = var.create ? azurerm_linux_virtual_machine.this[0].id : null }
output "principal_id" { value = var.create ? azurerm_linux_virtual_machine.this[0].identity[0].principal_id : null }
