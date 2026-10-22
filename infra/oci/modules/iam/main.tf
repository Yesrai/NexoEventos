variable "tenancy_ocid" { type = string }
variable "compartment_name" { type = string }
variable "uploader_group_name" { type = string }
variable "bucket_name" { type = string }
variable "freeform_tags" { type = map(string) }

resource "oci_identity_compartment" "this" {
  compartment_id = var.tenancy_ocid
  name           = var.compartment_name
  description    = "NexoEventos: recuperación (copias cifradas y simulacros)"
  enable_delete  = false
  freeform_tags  = var.freeform_tags
}

# Mínimo privilegio: el grupo solo puede crear/leer objetos de UN bucket; no puede borrar ni administrar el bucket.
resource "oci_identity_policy" "uploaders" {
  compartment_id = oci_identity_compartment.this.id
  name           = "nexoeventos-backup-uploaders"
  description    = "Escritura y lectura de objetos solo en el bucket de recuperación"
  statements = [
    "Allow group ${var.uploader_group_name} to read buckets in compartment ${oci_identity_compartment.this.name}",
    "Allow group ${var.uploader_group_name} to manage objects in compartment ${oci_identity_compartment.this.name} where all {target.bucket.name='${var.bucket_name}', any {request.permission='OBJECT_CREATE', request.permission='OBJECT_READ', request.permission='OBJECT_INSPECT'}}",
  ]
  freeform_tags = var.freeform_tags
}

output "compartment_id" { value = oci_identity_compartment.this.id }
