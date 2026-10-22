output "compartment_id" { value = module.iam.compartment_id }
output "bucket_name" { value = module.storage.bucket_name }
output "namespace" { value = module.storage.namespace }
output "private_subnet_id" { value = module.network.private_subnet_id }
output "recovery_vm_private_ip" { value = module.recovery.private_ip }
