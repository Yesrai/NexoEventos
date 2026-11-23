output "resource_group" { value = module.network.resource_group_name }
output "monitoring_vm_public_ip" { value = module.vm.public_ip }
output "log_analytics_workspace_id" { value = module.monitor.workspace_id }
output "monitoring_vm_fqdn" { value = module.vm.fqdn }
output "action_group_id" { value = module.monitor.action_group_id }
