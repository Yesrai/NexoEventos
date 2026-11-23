# Alarmas de disponibilidad de V2 OPCIONALES (desactivadas por defecto: con enable_alarms = false no se crea nada). Hoy V2 solo tiene las alarmas
# internas de la política de escalado (AlarmHigh/AlarmLow, que sí saltaron el 22-oct); NO hay alarmas de errores 5xx, destinos no sanos ni latencia,
# y la detección de caída solo se vio en el panel y en los registros de las pruebas. Coste: ≈ 0,10 USD/alarma/mes mientras V2 exista (las primeras
# 10 alarmas de la cuenta están en la capa gratuita). Para recibir correo, pasar el ARN del tema SNS de V1 (`alarm_topic_arn`).
variable "enable_alarms" {
  description = "Crea las alarmas de 5xx, destinos sanos/no sanos y latencia del ALB de V2."
  type        = bool
  default     = false
}

variable "alarm_topic_arn" {
  description = "ARN del tema SNS (p. ej. el creado en infra/aws con enable_alarms). Vacío = alarmas sin notificación."
  type        = string
  default     = ""
}

locals {
  alarm_actions = var.alarm_topic_arn != "" ? [var.alarm_topic_arn] : []
  alb_dimensions = {
    LoadBalancer = aws_lb.main.arn_suffix
    TargetGroup  = aws_lb_target_group.web.arn_suffix
  }
}

resource "aws_cloudwatch_metric_alarm" "alb_target_5xx" {
  count               = var.enable_alarms ? 1 : 0
  alarm_name          = "${local.v2_prefix}-alb-5xx-destino"
  alarm_description   = "Al menos 5 respuestas 5xx de los destinos por minuto en 2 de 3 minutos (caída de la API o de la base de datos)"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 3
  datapoints_to_alarm = 2
  metric_name         = "HTTPCode_Target_5XX_Count"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  statistic           = "Sum"
  threshold           = 5
  treat_missing_data  = "notBreaching" # sin tráfico no hay datos: no es una alarma
  dimensions          = { LoadBalancer = aws_lb.main.arn_suffix }
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "alb_unhealthy_hosts" {
  count               = var.enable_alarms ? 1 : 0
  alarm_name          = "${local.v2_prefix}-alb-destinos-no-sanos"
  alarm_description   = "Algún destino no sano durante 3 minutos seguidos"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 3
  metric_name         = "UnHealthyHostCount"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  statistic           = "Maximum"
  threshold           = 1
  treat_missing_data  = "notBreaching"
  dimensions          = local.alb_dimensions
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
}

# Destinos sanos por debajo de la capacidad DESEADA del grupo (no de un mínimo fijo): si se baja a 0 a propósito (como en las ventanas de prueba),
# no salta; si una instancia muere o se está reemplazando, salta tras 3 minutos. Es una expresión de métricas entre dos espacios de nombres.
resource "aws_cloudwatch_metric_alarm" "alb_healthy_below_desired" {
  count               = var.enable_alarms ? 1 : 0
  alarm_name          = "${local.v2_prefix}-alb-sanos-bajo-lo-deseado"
  alarm_description   = "Destinos sanos del ALB menores que la capacidad deseada del ASG durante 3 minutos (instancia caída o en reemplazo)"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 3
  threshold           = 1
  treat_missing_data  = "notBreaching" # grupo en 0 o sin destinos registrados a propósito: no es una alarma
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions

  metric_query {
    id          = "bajo"
    expression  = "IF(sanos < deseada, 1, 0)"
    label       = "Destinos sanos < capacidad deseada"
    return_data = true
  }
  metric_query {
    id = "sanos"
    metric {
      metric_name = "HealthyHostCount"
      namespace   = "AWS/ApplicationELB"
      period      = 60
      stat        = "Minimum"
      dimensions  = local.alb_dimensions
    }
  }
  metric_query {
    id = "deseada"
    metric {
      metric_name = "GroupDesiredCapacity"
      namespace   = "AWS/AutoScaling"
      period      = 60
      stat        = "Maximum"
      dimensions  = { AutoScalingGroupName = aws_autoscaling_group.web.name }
    }
  }
}

# Instancias en servicio por debajo de la capacidad deseada (fallo de lanzamiento o de instancia en el propio ASG; el ASG ya publica estas métricas).
resource "aws_cloudwatch_metric_alarm" "asg_in_service_below_desired" {
  count               = var.enable_alarms ? 1 : 0
  alarm_name          = "${local.v2_prefix}-asg-en-servicio-bajo-lo-deseado"
  alarm_description   = "Instancias InService del ASG menores que la capacidad deseada durante 5 minutos (un reemplazo normal tarda ≈ 2,5 min)"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 5
  threshold           = 1
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions

  metric_query {
    id          = "bajo"
    expression  = "IF(en_servicio < deseada, 1, 0)"
    label       = "InService < deseada"
    return_data = true
  }
  metric_query {
    id = "en_servicio"
    metric {
      metric_name = "GroupInServiceInstances"
      namespace   = "AWS/AutoScaling"
      period      = 60
      stat        = "Minimum"
      dimensions  = { AutoScalingGroupName = aws_autoscaling_group.web.name }
    }
  }
  metric_query {
    id = "deseada"
    metric {
      metric_name = "GroupDesiredCapacity"
      namespace   = "AWS/AutoScaling"
      period      = 60
      stat        = "Maximum"
      dimensions  = { AutoScalingGroupName = aws_autoscaling_group.web.name }
    }
  }
}

# Avisos del ASG (lanzamiento, terminación y sus errores): gratuitos; solo con un tema SNS existente.
resource "aws_autoscaling_notification" "events" {
  count       = var.enable_alarms && var.alarm_topic_arn != "" ? 1 : 0
  group_names = [aws_autoscaling_group.web.name]
  topic_arn   = var.alarm_topic_arn
  notifications = [
    "autoscaling:EC2_INSTANCE_LAUNCH",
    "autoscaling:EC2_INSTANCE_TERMINATE",
    "autoscaling:EC2_INSTANCE_LAUNCH_ERROR",
    "autoscaling:EC2_INSTANCE_TERMINATE_ERROR",
  ]
}

resource "aws_cloudwatch_metric_alarm" "alb_latency_p95" {
  count               = var.enable_alarms ? 1 : 0
  alarm_name          = "${local.v2_prefix}-alb-latencia-p95"
  alarm_description   = "Latencia p95 de los destinos mayor a 1,5 s en 3 de 5 minutos (el login con Argon2 es lento: la medición de 50 usuarios dio p95 ≈ 0,2–0,4 s)"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 5
  datapoints_to_alarm = 3
  metric_name         = "TargetResponseTime"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  extended_statistic  = "p95"
  threshold           = 1.5
  treat_missing_data  = "notBreaching"
  dimensions          = { LoadBalancer = aws_lb.main.arn_suffix }
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
}
