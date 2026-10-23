variable "compartment_id" { type = string }
variable "bucket_name" { type = string }
variable "freeform_tags" { type = map(string) }

# Sin compartment_id: con el compartimento recién creado el proveedor devuelve el namespace vacío; sin argumento usa el del tenancy.
data "oci_objectstorage_namespace" "this" {}

resource "oci_objectstorage_bucket" "recovery" {
  compartment_id = var.compartment_id
  namespace      = data.oci_objectstorage_namespace.this.namespace
  name           = var.bucket_name
  access_type    = "NoPublicAccess"
  storage_tier   = "Standard"
  versioning     = "Enabled"
  freeform_tags  = var.freeform_tags
}

output "bucket_name" { value = oci_objectstorage_bucket.recovery.name }
output "namespace" { value = data.oci_objectstorage_namespace.this.namespace }
