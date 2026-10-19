# Panel para medir escalado, reparto de carga y caída de una instancia (los mismos datos que recoge scripts/cloud/v2-measure.py).
resource "aws_cloudwatch_dashboard" "v2" {
  dashboard_name = "${local.v2_prefix}-medicion"
  dashboard_body = jsonencode({
    widgets = [
      {
        type = "metric", x = 0, y = 0, width = 12, height = 6
        properties = {
          title = "Instancias sanas y capacidad del grupo", region = var.aws_region, stat = "Average", period = 60
          metrics = [
            ["AWS/ApplicationELB", "HealthyHostCount", "TargetGroup", aws_lb_target_group.web.arn_suffix, "LoadBalancer", aws_lb.main.arn_suffix],
            [".", "UnHealthyHostCount", ".", ".", ".", "."],
            ["AWS/AutoScaling", "GroupInServiceInstances", "AutoScalingGroupName", aws_autoscaling_group.web.name],
            [".", "GroupDesiredCapacity", ".", "."],
          ]
        }
      },
      {
        type = "metric", x = 12, y = 0, width = 12, height = 6
        properties = {
          title = "Solicitudes, latencia y errores del ALB", region = var.aws_region, period = 60
          metrics = [
            ["AWS/ApplicationELB", "RequestCount", "LoadBalancer", aws_lb.main.arn_suffix, { stat = "Sum" }],
            [".", "TargetResponseTime", ".", ".", { stat = "p95", yAxis = "right" }],
            [".", "HTTPCode_Target_5XX_Count", ".", ".", { stat = "Sum" }],
            [".", "HTTPCode_ELB_5XX_Count", ".", ".", { stat = "Sum" }],
          ]
        }
      },
      {
        type = "metric", x = 0, y = 6, width = 12, height = 6
        properties = {
          title = "CPU media del grupo y créditos", region = var.aws_region, period = 60
          metrics = [
            ["AWS/EC2", "CPUUtilization", "AutoScalingGroupName", aws_autoscaling_group.web.name, { stat = "Average" }],
            [".", "CPUSurplusCreditBalance", ".", ".", { stat = "Maximum", yAxis = "right" }],
          ]
        }
      },
      {
        type = "metric", x = 12, y = 6, width = 12, height = 6
        properties = {
          title = "RDS: conexiones, CPU y memoria liberable", region = var.aws_region, period = 60
          metrics = [
            ["AWS/RDS", "DatabaseConnections", "DBInstanceIdentifier", "${local.name_prefix}-postgres", { stat = "Maximum" }],
            [".", "CPUUtilization", ".", ".", { stat = "Maximum", yAxis = "right" }],
            [".", "FreeableMemory", ".", ".", { stat = "Minimum", yAxis = "right" }],
          ]
        }
      },
    ]
  })
}
