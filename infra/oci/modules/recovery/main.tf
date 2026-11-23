variable "create" { type = bool }
variable "compartment_id" { type = string }
variable "subnet_id" { type = string }
variable "nsg_id" { type = string }
variable "shape" { type = string }
variable "ssh_public_key" { type = string }
variable "bastion_client_cidr" { type = string }
variable "freeform_tags" { type = map(string) }
variable "boot_volume_gb" { type = number }
variable "allow_trial_paid_shape" { type = bool }
variable "flex_ocpus" { type = number }
variable "flex_memory_gb" { type = number }
variable "assign_public_ip" {
  type    = bool
  default = false
}
variable "bastion_subnet_id" {
  type    = string
  default = ""
}

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

# VM TEMPORAL (create=false por defecto): sin IP pública (salvo assign_public_ip=true con la entrada de prueba), sin credenciales; se destruye tras cada simulacro.
resource "oci_core_instance" "recovery" {
  count               = var.create ? 1 : 0
  compartment_id      = var.compartment_id
  availability_domain = data.oci_identity_availability_domains.this.availability_domains[0].name
  shape               = var.shape
  display_name        = "nexoeventos-recovery-drill"
  create_vnic_details {
    subnet_id        = var.subnet_id
    assign_public_ip = var.assign_public_ip
    nsg_ids          = [var.nsg_id]
  }
  # Formas Flex (A1): tamaño explícito dentro de Always Free (máx. 4 OCPU / 24 GB en total). E2.1.Micro no lleva shape_config.
  dynamic "shape_config" {
    for_each = endswith(var.shape, ".Flex") ? [1] : []
    content {
      ocpus         = var.flex_ocpus
      memory_in_gbs = var.flex_memory_gb
    }
  }
  source_details {
    source_type             = "image"
    source_id               = data.oci_core_images.ol9[0].images[0].id
    boot_volume_size_in_gbs = var.boot_volume_gb
  }
  preserve_boot_volume = false
  instance_options {
    are_legacy_imds_endpoints_disabled = true
  }
  metadata = {
    ssh_authorized_keys = var.ssh_public_key
    # Primer arranque (cloud-init): neutraliza dnf-makecache y ksplice-agent antes de cualquier SSH; es un atributo de la MISMA instancia (no añade recursos).
    user_data = base64encode(file("${path.module}/cloud-init-quiesce.sh"))
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
      condition     = contains(["VM.Standard.E2.1.Micro", "VM.Standard.A1.Flex"], var.shape) || (var.allow_trial_paid_shape && var.shape == "VM.Standard.E5.Flex")
      error_message = "Solo formas Always Free (E2.1.Micro, A1.Flex) o, con allow_trial_paid_shape=true, VM.Standard.E5.Flex (créditos del Free Trial)."
    }
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
  target_subnet_id             = var.bastion_subnet_id != "" ? var.bastion_subnet_id : var.subnet_id
  name                         = "nexorecovery"
  client_cidr_block_allow_list = [var.bastion_client_cidr]
  max_session_ttl_in_seconds   = 3600
  freeform_tags                = var.freeform_tags
}

output "instance_id" { value = var.create ? oci_core_instance.recovery[0].id : null }
output "private_ip" { value = var.create ? oci_core_instance.recovery[0].private_ip : null }
