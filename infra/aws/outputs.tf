output "region" { value = var.aws_region }
output "vpc_id" { value = aws_vpc.main.id }
output "app_public_ip" {
  value       = aws_instance.app.public_ip
  description = "IP dinámica; HTTPS confiable requiere dominio y certificado."
}
output "rds_endpoint" {
  value       = aws_db_instance.postgres.address
  description = "Endpoint privado accesible solo desde el SG de aplicación."
}
output "private_bucket_name" { value = aws_s3_bucket.private.id }
