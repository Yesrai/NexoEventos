variable "tenancy_ocid" { type = string }
variable "compartment_name" { type = string }
variable "uploader_group_name" { type = string }
variable "bucket_name" { type = string }
variable "uploader_user_name" { type = string }
variable "uploader_user_email" {
  type      = string
  sensitive = true
}
variable "freeform_tags" { type = map(string) }

resource "oci_identity_compartment" "this" {
  compartment_id = var.tenancy_ocid
  name           = var.compartment_name
  description    = "NexoEventos: recuperación (copias cifradas y simulacros)"
  enable_delete  = false
  freeform_tags  = var.freeform_tags
}

# Identidad de carga: grupo y usuario de servicio en el dominio Default. El usuario solo puede usar una clave API (sin consola, sin tokens, sin SMTP,
# sin credenciales de BD). La clave API NO se crea aquí: la genera la operadora fuera del repositorio y la registra a mano (ver README).
resource "oci_identity_group" "uploaders" {
  compartment_id = var.tenancy_ocid
  name           = var.uploader_group_name
  description    = "NexoEventos: carga de copias cifradas al bucket de recuperación"
  freeform_tags  = var.freeform_tags
}

resource "oci_identity_user" "uploader" {
  compartment_id = var.tenancy_ocid
  name           = var.uploader_user_name
  email          = var.uploader_user_email
  description    = "NexoEventos: identidad de servicio para cargar copias cifradas (solo clave API)"
  freeform_tags  = var.freeform_tags
}

resource "oci_identity_user_capabilities_management" "uploader" {
  user_id                      = oci_identity_user.uploader.id
  can_use_api_keys             = true
  can_use_auth_tokens          = false
  can_use_console_password     = false
  can_use_customer_secret_keys = false
  can_use_smtp_credentials     = false
}

resource "oci_identity_user_group_membership" "uploader" {
  group_id = oci_identity_group.uploaders.id
  user_id  = oci_identity_user.uploader.id
}

# Mínimo privilegio: el grupo solo puede crear/leer objetos de UN bucket; no puede borrar ni administrar el bucket.
resource "oci_identity_policy" "uploaders" {
  compartment_id = oci_identity_compartment.this.id
  name           = "nexoeventos-backup-uploaders"
  description    = "Escritura y lectura de objetos solo en el bucket de recuperación"
  statements = [
    "Allow group ${var.uploader_group_name} to read buckets in compartment ${oci_identity_compartment.this.name} where target.bucket.name='${var.bucket_name}'",
    "Allow group ${var.uploader_group_name} to manage objects in compartment ${oci_identity_compartment.this.name} where all {target.bucket.name='${var.bucket_name}', any {request.permission='OBJECT_CREATE', request.permission='OBJECT_READ', request.permission='OBJECT_INSPECT'}}",
  ]
  freeform_tags = var.freeform_tags
  depends_on    = [oci_identity_group.uploaders]
}

output "compartment_id" { value = oci_identity_compartment.this.id }
output "uploader_user_name" { value = oci_identity_user.uploader.name }
