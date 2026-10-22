variable "create" { type = bool }
variable "compartment_id" { type = string }
variable "subnet_id" { type = string }
variable "nsg_id" { type = string }
variable "shape" { type = string }
variable "ssh_public_key" { type = string }
variable "bastion_client_cidr" { type = string }
variable "freeform_tags" { type = map(string) }

data "oci_identity_availability_domains" "this" {
  compartment_id = var.compartment_id
}

data "oci_core_images" "ol9" {
  count                    = var.create ? 1 : 0
  compartment_id           = var.compartment_id
  operating_system         = "Oracle Linux"
  operating_system_version = "9"
  shape                    = var.shape
  sort_by                  = "TIMECREATED"
  sort_order               = "DESC"
}

# VM TEMPORAL (create=false por defecto): sin IP pública, sin credenciales; se destruye tras cada simulacro.
resource "oci_core_instance" "recovery" {
  count               = var.create ? 1 : 0
  compartment_id      = var.compartment_id
  availability_domain = data.oci_identity_availability_domains.this.availability_domains[0].name
  shape               = var.shape
  display_name        = "nexoeventos-recovery-drill"
  create_vnic_details {
    subnet_id        = var.subnet_id
    assign_public_ip = false
    nsg_ids          = [var.nsg_id]
  }
  source_details {
    source_type = "image"
    source_id   = data.oci_core_images.ol9[0].images[0].id
  }
  metadata = {
    ssh_authorized_keys = var.ssh_public_key
  }
  agent_config {
    plugins_config {
      name          = "Bastion"
      desired_state = "ENABLED"
    }
  }
  freeform_tags = var.freeform_tags

  lifecycle {
    precondition {
      condition     = var.ssh_public_key != ""
      error_message = "Se requiere la clave PÚBLICA SSH del operador para crear la VM de recuperación."
    }
  }
}

resource "oci_bastion_bastion" "this" {
  count                        = var.create && var.bastion_client_cidr != "" ? 1 : 0
  bastion_type                 = "STANDARD"
  compartment_id               = var.compartment_id
  target_subnet_id             = var.subnet_id
  name                         = "nexorecovery"
  client_cidr_block_allow_list = [var.bastion_client_cidr]
  max_session_ttl_in_seconds   = 3600
  freeform_tags                = var.freeform_tags
}

output "private_ip" { value = var.create ? oci_core_instance.recovery[0].private_ip : null }
