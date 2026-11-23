# Alarmas de CloudWatch y notificaciones OPCIONALES para V1/RDS (desactivadas por defecto: con enable_alarms = false no se crea nada nuevo).
# Hoy solo existe `ec2_cpu_high`, sin acciones (nadie recibe aviso) y nunca ha saltado; no hay alarma de espacio libre de la RDS (el aviso de
# «20 GiB / umbral máximo 20 GiB» es de configuración y no mide espacio libre). Coste si se activa: CloudWatch cobra ≈ 0,10 USD/alarma/mes
# (las primeras 10 entran en la capa gratuita) y SNS por correo es gratuito.
# EL CORREO NO ESTÁ EN TERRAFORM A PROPÓSITO: un `aws_sns_topic_subscription` guardaría la dirección en texto claro en el estado y en cualquier plan
# guardado. La suscripción se crea con `scripts/cloud/suscribir-correo-alarmas.sh` (entrada oculta en la terminal, sin imprimir ni registrar la dirección)
# y exige confirmar el mensaje que envía AWS.
variable "enable_alarms" {
  description = "Crea el tema SNS, las alarmas de la RDS y de la EC2, la suscripción a eventos de RDS y las acciones de la alarma de CPU de la EC2."
  type        = bool
  default     = false
}

variable "rds_free_storage_alarm_bytes" {
  description = "Umbral de FreeStorageSpace (bytes) por debajo del cual salta la alarma. Por defecto 2 GiB (10 % de 20 GiB)."
  type        = number
  default     = 2147483648
  validation {
    condition     = var.rds_free_storage_alarm_bytes >= 536870912
    error_message = "El umbral debe ser de al menos 512 MiB."
  }
}

variable "rds_freeable_memory_alarm_bytes" {
  description = "Umbral de FreeableMemory (bytes) por debajo del cual salta la alarma. Por defecto 100 MiB: el mínimo histórico por minuto fue 166 MiB (23-oct, durante el failover) y lo normal 186–275 MiB en una db.t3.micro de 1 GiB."
  type        = number
  default     = 104857600
  validation {
    condition     = var.rds_freeable_memory_alarm_bytes >= 33554432
    error_message = "El umbral debe ser de al menos 32 MiB."
  }
}

locals {
  alarms_notify = var.enable_alarms
  alarm_actions = local.alarms_notify ? [aws_sns_topic.alarms[0].arn] : []
}

resource "aws_sns_topic" "alarms" {
  count = local.alarms_notify ? 1 : 0
  name  = "${local.name_prefix}-alarmas"
}

resource "aws_cloudwatch_metric_alarm" "rds_free_storage_low" {
  count               = var.enable_alarms ? 1 : 0
  alarm_name          = "${local.name_prefix}-rds-espacio-libre-bajo"
  alarm_description   = "FreeStorageSpace de la RDS por debajo del umbral (medición real del espacio libre; el aviso de 20 GiB de RDS es solo de configuración)"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 2
  metric_name         = "FreeStorageSpace"
  namespace           = "AWS/RDS"
  period              = 300
  statistic           = "Minimum"
  threshold           = var.rds_free_storage_alarm_bytes
  treat_missing_data  = "missing" # con la RDS detenida no hay datos: no es una alarma
  dimensions          = { DBInstanceIdentifier = aws_db_instance.postgres.identifier }
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
}

# Memoria liberable de la RDS: es el recurso más ajustado (el disco tiene ≈ 85 % libre). Se usa el mínimo de cada periodo de 5 min y se exigen 3 periodos
# seguidos (15 min) para no saltar con un pico puntual; con la RDS detenida no hay datos y no salta.
resource "aws_cloudwatch_metric_alarm" "rds_freeable_memory_low" {
  count               = var.enable_alarms ? 1 : 0
  alarm_name          = "${local.name_prefix}-rds-memoria-liberable-baja"
  alarm_description   = "FreeableMemory de la RDS por debajo del umbral (por defecto 100 MiB) durante 15 minutos; el mínimo histórico por minuto fue 166 MiB"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 3
  metric_name         = "FreeableMemory"
  namespace           = "AWS/RDS"
  period              = 300
  statistic           = "Minimum"
  threshold           = var.rds_freeable_memory_alarm_bytes
  treat_missing_data  = "missing"
  dimensions          = { DBInstanceIdentifier = aws_db_instance.postgres.identifier }
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "rds_cpu_high" {
  count               = var.enable_alarms ? 1 : 0
  alarm_name          = "${local.name_prefix}-rds-cpu-alta"
  alarm_description   = "CPU de la RDS mayor a 80 por ciento durante 15 minutos"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "CPUUtilization"
  namespace           = "AWS/RDS"
  period              = 300
  statistic           = "Average"
  threshold           = 80
  treat_missing_data  = "missing"
  dimensions          = { DBInstanceIdentifier = aws_db_instance.postgres.identifier }
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
}

# Fallo de las comprobaciones de estado de la EC2 de V1 (hardware o sistema operativo no responden). Con la instancia detenida no hay datos: no salta.
resource "aws_cloudwatch_metric_alarm" "ec2_status_check_failed" {
  count               = var.enable_alarms ? 1 : 0
  alarm_name          = "${local.name_prefix}-ec2-comprobaciones-fallidas"
  alarm_description   = "StatusCheckFailed >= 1 durante 3 minutos en la EC2 de V1"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 3
  metric_name         = "StatusCheckFailed"
  namespace           = "AWS/EC2"
  period              = 60
  statistic           = "Maximum"
  threshold           = 1
  treat_missing_data  = "notBreaching"
  dimensions          = { InstanceId = aws_instance.app.id }
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
}

# Eventos de la RDS por SNS (gratuito): failover, fallos, espacio bajo y notificaciones. La categoría «low storage» es la que AWS usa para el aviso de
# «almacenamiento cerca del umbral máximo» (A16). RDS necesita permiso para publicar en el tema.
data "aws_iam_policy_document" "alarms_topic" {
  count = local.alarms_notify ? 1 : 0
  statement {
    sid       = "PermitirEventosDeRDS"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.alarms[0].arn]
    principals {
      type        = "Service"
      identifiers = ["events.rds.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
  statement {
    sid       = "PermitirCloudWatch"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.alarms[0].arn]
    principals {
      type        = "Service"
      identifiers = ["cloudwatch.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_sns_topic_policy" "alarms" {
  count  = local.alarms_notify ? 1 : 0
  arn    = aws_sns_topic.alarms[0].arn
  policy = data.aws_iam_policy_document.alarms_topic[0].json
}

resource "aws_db_event_subscription" "rds" {
  count            = local.alarms_notify ? 1 : 0
  name             = "${local.name_prefix}-rds-eventos"
  sns_topic        = aws_sns_topic.alarms[0].arn
  source_type      = "db-instance"
  source_ids       = [aws_db_instance.postgres.identifier]
  event_categories = ["failover", "failure", "low storage", "notification", "availability"]
  depends_on       = [aws_sns_topic_policy.alarms]
}
