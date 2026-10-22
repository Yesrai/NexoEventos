output "resource_group" { value = module.network.resource_group_name }
output "monitoring_vm_public_ip" { value = module.vm.public_ip }
output "log_analytics_workspace_id" { value = module.monitor.workspace_id }
