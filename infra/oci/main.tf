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

module "recovery" {
  source                 = "./modules/recovery"
  create                 = var.create_recovery_vm
  compartment_id         = module.iam.compartment_id
  subnet_id              = module.network.private_subnet_id
  nsg_id                 = module.network.nsg_id
  shape                  = var.recovery_shape
  ssh_public_key         = var.ssh_public_key
  bastion_client_cidr    = var.bastion_client_cidr
  boot_volume_gb         = var.recovery_boot_volume_gb
  allow_trial_paid_shape = var.allow_trial_paid_shape
  flex_ocpus             = var.recovery_flex_ocpus
  flex_memory_gb         = var.recovery_flex_memory_gb
  freeform_tags          = local.common_tags
}
