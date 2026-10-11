output "recovery_instance_id" {
  value     = aws_instance.app.id
  sensitive = true
}

output "recovery_public_ip" {
  value     = aws_instance.app.public_ip
  sensitive = true
}

output "recovery_db_identifier" {
  value = aws_db_instance.recovery.identifier
}

output "recovery_db_endpoint" {
  value     = aws_db_instance.recovery.endpoint
  sensitive = true
}

output "recovery_fqdn" {
  description = "Hostname efímero que resuelve la IPv4 temporal sin cambiar el DNS principal."
  value       = "nexoeventos-recovery-${replace(aws_instance.app.public_ip, ".", "-")}.sslip.io"
}
