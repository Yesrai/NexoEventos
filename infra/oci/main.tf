module "iam" {
  source              = "./modules/iam"
  tenancy_ocid        = var.tenancy_ocid
  compartment_name    = var.compartment_name
  uploader_group_name = var.uploader_group_name
  uploader_user_name  = var.uploader_user_name
  uploader_user_email = var.uploader_user_email
  bucket_name         = var.bucket_name
  freeform_tags       = local.common_tags
}

module "network" {
  source             = "./modules/network"
  compartment_id     = module.iam.compartment_id
  vcn_cidr           = var.vcn_cidr
  subnet_cidr        = var.private_subnet_cidr
  enable_nat_gateway = var.enable_nat_gateway
  app_https_enabled  = var.app_https_enabled
  freeform_tags      = local.common_tags
}

module "storage" {
  source         = "./modules/storage"
  compartment_id = module.iam.compartment_id
  bucket_name    = var.bucket_name
  freeform_tags  = local.common_tags
}

# Entrada pública de PRUEBA (apagada por defecto; con create_public_entry = false no se crea nada y la VCN sigue sin Internet Gateway).
module "public_entry" {
  source              = "./modules/public_entry"
  create              = var.create_public_entry
  compartment_id      = module.iam.compartment_id
  vcn_id              = module.network.vcn_id
  subnet_cidr         = var.public_subnet_cidr
  allowed_https_cidrs = var.entry_allowed_cidrs
  bastion_source_cidr = var.public_subnet_cidr # el Bastion se crea en la subred pública (bastion_subnet_id) y de ahí sale su tráfico SSH
  freeform_tags       = local.common_tags
}

module "recovery" {
  source                 = "./modules/recovery"
  create                 = var.create_recovery_vm
  compartment_id         = module.iam.compartment_id
  subnet_id              = var.create_public_entry ? module.public_entry.subnet_id : module.network.private_subnet_id
  nsg_id                 = var.create_public_entry ? module.public_entry.nsg_id : module.network.nsg_id
  assign_public_ip       = var.create_public_entry
  bastion_subnet_id      = var.create_public_entry ? module.public_entry.subnet_id : ""
  shape                  = var.recovery_shape
  ssh_public_key         = var.ssh_public_key
  bastion_client_cidr    = var.bastion_client_cidr
  boot_volume_gb         = var.recovery_boot_volume_gb
  allow_trial_paid_shape = var.allow_trial_paid_shape
  flex_ocpus             = var.recovery_flex_ocpus
  flex_memory_gb         = var.recovery_flex_memory_gb
  freeform_tags          = local.common_tags
}

# Autoprueba del lease (B-10): apagado por defecto; nada se crea con create_lease_test = false.
module "lease" {
  source           = "./modules/lease"
  create           = var.create_lease_test
  tenancy_ocid     = var.tenancy_ocid
  compartment_id   = module.iam.compartment_id
  compartment_name = var.compartment_name
  bucket_name      = var.lease_bucket_name
  group_name       = "nexoeventos-lease-writers"
  user_name        = "nexoeventos-lease-svc"
  user_email       = var.uploader_user_email
  freeform_tags    = local.common_tags
}
