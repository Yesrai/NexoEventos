# AUTOPRUEBA DEL LEASE (B-10): bucket de PRUEBAS sin versionado + identidad dedicada con permiso de sobrescritura SOLO sobre ese bucket.
# Todo el módulo está apagado por defecto (create = false): no crea nada hasta que se pida expresamente y se revise el plan. NO se ha aplicado.
variable "create" { type = bool }
variable "tenancy_ocid" { type = string }
variable "compartment_id" { type = string }
variable "compartment_name" { type = string }
variable "bucket_name" { type = string }
variable "group_name" { type = string }
variable "user_name" { type = string }
variable "user_email" {
  type      = string
  sensitive = true
}
variable "freeform_tags" { type = map(string) }

# Con create = false tampoco se consulta el namespace: el módulo apagado no hace ninguna llamada a OCI.
data "oci_objectstorage_namespace" "this" {
  count = var.create ? 1 : 0
}

# SIN versionado a propósito: con versionado cada renovación crearía una versión nueva y el bucket de respaldos (versionado) no permite sobrescribir.
resource "oci_objectstorage_bucket" "lease_test" {
  count          = var.create ? 1 : 0
  compartment_id = var.compartment_id
  namespace      = data.oci_objectstorage_namespace.this[0].namespace
  name           = var.bucket_name
  access_type    = "NoPublicAccess"
  storage_tier   = "Standard"
  versioning     = "Disabled"
  freeform_tags  = var.freeform_tags

  lifecycle {
    precondition {
      condition     = can(regex("^nexoeventos-lease-test(-[a-z0-9]{1,12})?$", var.bucket_name))
      error_message = "El bucket de la autoprueba debe llamarse nexoeventos-lease-test[-sufijo] (jamás el bucket de respaldos)."
    }
  }
}

resource "oci_identity_group" "lease" {
  count          = var.create ? 1 : 0
  compartment_id = var.tenancy_ocid
  name           = var.group_name
  description    = "NexoEventos: autoprueba y lease de escritor único (solo objetos del bucket de pruebas)"
  freeform_tags  = var.freeform_tags
}

resource "oci_identity_user" "lease" {
  count          = var.create ? 1 : 0
  compartment_id = var.tenancy_ocid
  name           = var.user_name
  email          = var.user_email
  description    = "NexoEventos: identidad de servicio del lease (solo clave API)"
  freeform_tags  = var.freeform_tags
}

resource "oci_identity_user_capabilities_management" "lease" {
  count                        = var.create ? 1 : 0
  user_id                      = oci_identity_user.lease[0].id
  can_use_api_keys             = true
  can_use_auth_tokens          = false
  can_use_console_password     = false
  can_use_customer_secret_keys = false
  can_use_smtp_credentials     = false
}

resource "oci_identity_user_group_membership" "lease" {
  count    = var.create ? 1 : 0
  group_id = oci_identity_group.lease[0].id
  user_id  = oci_identity_user.lease[0].id
}

# Mínimo privilegio: leer el bucket y crear/leer/SOBRESCRIBIR objetos de ESE bucket. Sin permiso de borrado (la limpieza la hace el administrador) y sin administrar el bucket.
resource "oci_identity_policy" "lease" {
  count          = var.create ? 1 : 0
  compartment_id = var.compartment_id
  name           = "nexoeventos-lease-writers"
  description    = "Lease de escritor único: objetos del bucket de pruebas, sin borrado"
  statements = [
    "Allow group ${var.group_name} to read buckets in compartment ${var.compartment_name} where target.bucket.name='${var.bucket_name}'",
    "Allow group ${var.group_name} to manage objects in compartment ${var.compartment_name} where all {target.bucket.name='${var.bucket_name}', any {request.permission='OBJECT_INSPECT', request.permission='OBJECT_READ', request.permission='OBJECT_CREATE', request.permission='OBJECT_OVERWRITE'}}"
  ]
  freeform_tags = var.freeform_tags
  depends_on    = [oci_identity_group.lease]
}

output "lease_bucket_name" { value = var.create ? oci_objectstorage_bucket.lease_test[0].name : null }
output "lease_user_name" { value = var.create ? oci_identity_user.lease[0].name : null }
