terraform {
  required_version = ">= 1.16.0, < 2.0.0"
  # Estado SEPARADO del de V1 (infra/aws): esta raíz solo añade recursos y lee V1 con `data`.
  # El archivo de estado debe quedar con permisos restrictivos (por ejemplo work/terraform-state/academy-v2) y nunca en Git.
  backend "local" {}
  required_providers {
    aws = { source = "hashicorp/aws", version = "= 6.67.0" }
  }
}

provider "aws" {
  region = var.aws_region
  default_tags { tags = local.common_tags }
}

check "expected_aws_account" {
  assert {
    condition     = data.aws_caller_identity.current.account_id == var.expected_account_id
    error_message = "La identidad AWS activa no corresponde a la cuenta esperada del entorno. Operación cancelada."
  }
}
