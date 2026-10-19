output "alb_dns_name" {
  description = "DNS del ALB (k6 lo resuelve con --add-host para conservar el nombre y el certificado)."
  value       = aws_lb.main.dns_name
}

output "alb_arn_suffix" { value = aws_lb.main.arn_suffix }
output "target_group_arn_suffix" { value = aws_lb_target_group.web.arn_suffix }
output "asg_name" { value = aws_autoscaling_group.web.name }
output "web_security_group_id" { value = aws_security_group.web.id }
output "alb_security_group_id" { value = aws_security_group.alb.id }
output "public_subnets" { value = [data.aws_subnet.public_a.id, aws_subnet.public_b.id] }
