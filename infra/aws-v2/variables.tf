variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "expected_account_id" {
  description = "ID de 12 dígitos de la cuenta autorizada. Se mantiene en un tfvars local ignorado por Git."
  type        = string
  sensitive   = true
  validation {
    condition     = can(regex("^[0-9]{12}$", var.expected_account_id))
    error_message = "expected_account_id debe contener exactamente 12 dígitos."
  }
}

variable "project_slug" {
  type    = string
  default = "nexoeventos"
}

variable "environment" {
  description = "Debe coincidir con el entorno V1 del que se leen VPC, RDS y grupo de seguridad de la base."
  type        = string
  default     = "academy"
}

variable "public_b_cidr" {
  description = "Subred pública nueva en la segunda zona de disponibilidad (V1 usa 10.20.1.0/24 en la primera)."
  type        = string
  default     = "10.20.2.0/24"
}

variable "ami_id" {
  description = "AMI dorada de V2 (Amazon Linux 2023 + Nginx + FastAPI, SIN secretos ni certificados), creada fuera de Terraform."
  type        = string
  validation {
    condition     = can(regex("^ami-[0-9a-f]{8,17}$", var.ami_id))
    error_message = "ami_id debe tener el formato ami-xxxxxxxx."
  }
}

variable "instance_type" {
  type    = string
  default = "t3.small"
}

variable "root_volume_gib" {
  type    = number
  default = 20
}

variable "instance_profile_name" {
  description = "Perfil de instancia del laboratorio (LabInstanceProfile); no se crean roles IAM."
  type        = string
  default     = "LabInstanceProfile"
}

variable "cpu_credits_mode" {
  description = "unlimited iguala a V1 (comparable) pero puede facturar créditos excedentes; standard limita la CPU al agotarse."
  type        = string
  default     = "unlimited"
  validation {
    condition     = contains(["unlimited", "standard"], var.cpu_credits_mode)
    error_message = "cpu_credits_mode debe ser unlimited o standard."
  }
}

variable "certificate_arn" {
  description = "ARN del certificado en ACM (importado: ver deploy/v2/import-acm-certificate-on-v1.sh). Sin él no hay listener HTTPS."
  type        = string
  validation {
    condition     = can(regex("^arn:aws:acm:[a-z0-9-]+:[0-9]{12}:certificate/[0-9a-f-]+$", var.certificate_arn))
    error_message = "certificate_arn debe ser el ARN de un certificado ACM."
  }
}

variable "app_secret_name" {
  description = "Nombre del secreto de Secrets Manager con el archivo backend.env compartido (se crea fuera de Terraform: deploy/v2/create-shared-secret-on-v1.sh)."
  type        = string
  default     = "nexoeventos/academy/backend-env"
}

variable "asg_enabled" {
  description = "OBLIGATORIA, sin valor por defecto (a propósito, para que V2 no se encienda por accidente). true = V2 encendida (asg_min/asg_desired instancias, 2 por defecto); false = V2 apagada: el ASG queda con mínima=0 y deseada=0 (la máxima se conserva). Con false siguen existiendo y facturando el ALB y la RDS. Usar siempre scripts/v2-ops/v2-terraform.sh on|off (archivos academy-v2-on.tfvars / academy-v2-off.tfvars); ver docs/operacion/reencendido-v2.md."
  type        = bool
}

variable "asg_min" {
  type    = number
  default = 2
}

variable "asg_max" {
  type    = number
  default = 3
}

variable "asg_desired" {
  type    = number
  default = 2
}

variable "scale_cpu_target_pct" {
  description = "Objetivo de CPU media del grupo para la política de seguimiento (V1 midió ~38 % con 50 usuarios en una instancia; bájelo, p. ej. 15, para forzar un escalado en la demostración)."
  type        = number
  default     = 40
}

variable "scale_requests_per_target" {
  description = "Solicitudes por minuto y por instancia para una segunda política (0 la desactiva)."
  type        = number
  default     = 0
}

variable "rds_ca_sha256" {
  description = "Huellas SHA-256 (públicas) de las CA de RDS que el arranque acepta del paquete regional. Por defecto: rds-ca-rsa2048-g1 de us-east-1, la CA de la RDS de V1. Se comprobó con `aws rds describe-certificates` (huella SHA-1 del API autenticado = la del certificado del paquete). Si RDS cambia de CA, el arranque FALLA a propósito hasta actualizar esta lista."
  type        = list(string)
  default     = ["e4ce41d069f4bdcdb714259058961ee42ed18cf2bf627a3d647aff25437d4b68"]
  validation {
    condition     = length(var.rds_ca_sha256) > 0 && alltrue([for p in var.rds_ca_sha256 : can(regex("^[0-9a-f]{64}$", p))])
    error_message = "rds_ca_sha256 debe contener huellas SHA-256 en hexadecimal minúscula (64 caracteres)."
  }
}

variable "db_pool_size" {
  description = "Conexiones permanentes del pool de cada worker (2 workers por instancia)."
  type        = number
  default     = 5
}

variable "db_max_overflow" {
  description = "Conexiones adicionales por worker. Con 3 instancias: 3 x 2 x (5+5) = 60 de las 81 que admite la db.t3.micro."
  type        = number
  default     = 5
}

variable "alb_deletion_protection" {
  type    = bool
  default = false
}

locals {
  name_prefix = "${var.project_slug}-${var.environment}"
  v2_prefix   = "${var.project_slug}-${var.environment}-v2"
  common_tags = {
    Project     = "NexoEventos"
    Environment = var.environment
    Stack       = "v2"
    ManagedBy   = "Terraform"
  }
}

variable "ami_includes_livez" {
  description = "true SOLO cuando la AMI de las instancias ya trae la ruta /livez de Nginx (AMI reconstruida con ansible/playbooks/bake-v2.yml e instancias rotadas). Con false el ALB usa /healthz (readiness con PostgreSQL), que existe en todas las AMI. Con una AMI antigua, /livez caería en try_files -> index.html y devolvería 200 aunque la API estuviera muerta (falsa salud)."
  type        = bool
  default     = false
}

# --- T5: ajustes de detección del ALB (los valores por defecto CONSERVAN el comportamiento actual) ---
variable "alb_health_interval" {
  description = "Segundos entre comprobaciones de salud del ALB por destino (el ALB admite 5–300). Por defecto 10 (comportamiento histórico)."
  type        = number
  default     = 10
  validation {
    condition     = var.alb_health_interval >= 5 && var.alb_health_interval <= 300
    error_message = "alb_health_interval debe estar entre 5 y 300 s (límites del ALB)."
  }
}

variable "alb_health_timeout" {
  description = "Segundos sin respuesta para que una comprobación cuente como fallo (el ALB admite 2–120). Aquí se exige además < intervalo."
  type        = number
  default     = 5
  validation {
    condition     = var.alb_health_timeout >= 2 && var.alb_health_timeout <= 120 && var.alb_health_timeout < var.alb_health_interval
    error_message = "alb_health_timeout debe estar entre 2 y 120 s y ser menor que alb_health_interval."
  }
}

variable "alb_lb_algorithm" {
  description = "Algoritmo del grupo de destino: round_robin, least_outstanding_requests (actual) o weighted_random (necesario para la mitigación automática de anomalías, ATW)."
  type        = string
  default     = "least_outstanding_requests"
  validation {
    condition     = contains(["round_robin", "least_outstanding_requests", "weighted_random"], var.alb_lb_algorithm)
    error_message = "alb_lb_algorithm debe ser round_robin, least_outstanding_requests o weighted_random."
  }
}

variable "alb_anomaly_mitigation" {
  description = "Mitigación automática de anomalías del ALB (Automatic Target Weights): on|off. Solo con alb_lb_algorithm=weighted_random y, según AWS, con ≥ 3 destinos sanos (asg_desired ≥ 3). Detecta 5xx/errores de conexión de un destino frente a sus pares, independiente de las comprobaciones de salud; reduce su tráfico en pasos periódicos (cada 5 s); AWS no publica un tiempo garantizado."
  type        = string
  default     = "off"
  validation {
    condition     = contains(["on", "off"], var.alb_anomaly_mitigation)
    error_message = "alb_anomaly_mitigation debe ser on u off."
  }
  validation {
    condition     = var.alb_anomaly_mitigation == "off" || var.alb_lb_algorithm == "weighted_random"
    error_message = "La mitigación de anomalías exige alb_lb_algorithm = weighted_random."
  }
}
