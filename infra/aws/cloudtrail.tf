# CloudTrail persistente (OPCIONAL, desactivado por defecto): hoy la cuenta solo tiene el «Historial de eventos» de 90 días (captura A9: sin trails).
# Con enable_cloudtrail = false este archivo no crea nada. Antes de activarlo hay que comprobar con una sesión de Academy que cloudtrail:CreateTrail está
# permitido (el LabRole puede denegarlo) y revisar el coste: el primer trail de eventos de gestión es gratuito; solo se paga el almacenamiento S3 (con una
# caducidad de 90 días es de centavos al mes). No se aplica sin autorización explícita.
variable "enable_cloudtrail" {
  description = "Crea un trail de eventos de gestión con validación de integridad y su bucket S3 privado. Requiere permisos que AWS Academy puede denegar."
  type        = bool
  default     = false
}

variable "cloudtrail_retention_days" {
  description = "Días que se conservan los registros del trail en S3."
  type        = number
  default     = 90
  validation {
    condition     = var.cloudtrail_retention_days >= 30 && var.cloudtrail_retention_days <= 365
    error_message = "La retención debe estar entre 30 y 365 días."
  }
}

locals {
  cloudtrail_name = "${local.name_prefix}-trail"
  cloudtrail_arn  = "arn:aws:cloudtrail:${var.aws_region}:${data.aws_caller_identity.current.account_id}:trail/${local.cloudtrail_name}"
}

resource "aws_s3_bucket" "cloudtrail" {
  count         = var.enable_cloudtrail ? 1 : 0
  bucket        = "${local.name_prefix}-trail-${data.aws_caller_identity.current.account_id}-${var.aws_region}"
  force_destroy = false
  tags          = { Name = "${local.name_prefix}-trail" }
}

resource "aws_s3_bucket_public_access_block" "cloudtrail" {
  count                   = var.enable_cloudtrail ? 1 : 0
  bucket                  = aws_s3_bucket.cloudtrail[0].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "cloudtrail" {
  count  = var.enable_cloudtrail ? 1 : 0
  bucket = aws_s3_bucket.cloudtrail[0].id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "cloudtrail" {
  count  = var.enable_cloudtrail ? 1 : 0
  bucket = aws_s3_bucket.cloudtrail[0].id
  rule {
    id     = "expire-trail-logs"
    status = "Enabled"
    filter {
      prefix = "AWSLogs/"
    }
    expiration {
      days = var.cloudtrail_retention_days
    }
  }
}

data "aws_iam_policy_document" "cloudtrail_bucket" {
  count = var.enable_cloudtrail ? 1 : 0
  statement {
    sid       = "CloudTrailAclCheck"
    actions   = ["s3:GetBucketAcl"]
    resources = [aws_s3_bucket.cloudtrail[0].arn]
    principals {
      type        = "Service"
      identifiers = ["cloudtrail.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceArn"
      values   = [local.cloudtrail_arn]
    }
  }
  statement {
    sid       = "CloudTrailWrite"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.cloudtrail[0].arn}/AWSLogs/${data.aws_caller_identity.current.account_id}/*"]
    principals {
      type        = "Service"
      identifiers = ["cloudtrail.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "s3:x-amz-acl"
      values   = ["bucket-owner-full-control"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceArn"
      values   = [local.cloudtrail_arn]
    }
  }
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.cloudtrail[0].arn, "${aws_s3_bucket.cloudtrail[0].arn}/*"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "cloudtrail" {
  count  = var.enable_cloudtrail ? 1 : 0
  bucket = aws_s3_bucket.cloudtrail[0].id
  policy = data.aws_iam_policy_document.cloudtrail_bucket[0].json
  depends_on = [
    aws_s3_bucket_public_access_block.cloudtrail,
  ]
}

resource "aws_cloudtrail" "main" {
  count                         = var.enable_cloudtrail ? 1 : 0
  name                          = local.cloudtrail_name
  s3_bucket_name                = aws_s3_bucket.cloudtrail[0].id
  include_global_service_events = true
  is_multi_region_trail         = false
  enable_log_file_validation    = true
  tags                          = { Name = local.cloudtrail_name }
  depends_on                    = [aws_s3_bucket_policy.cloudtrail]
}
