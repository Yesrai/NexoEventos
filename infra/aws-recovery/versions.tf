terraform {
  required_version = ">= 1.16.0, < 2.0.0"
  backend "local" {}
  required_providers {
    aws = { source = "hashicorp/aws", version = "= 6.67.0" }
  }
}

provider "aws" {
  region              = var.aws_region
  allowed_account_ids = [var.expected_account_id]
  default_tags { tags = local.common_tags }
}

data "aws_caller_identity" "current" {}

check "expected_aws_account" {
  assert {
    condition     = data.aws_caller_identity.current.account_id == var.expected_account_id
    error_message = "La cuenta AWS activa no coincide con la cuenta autorizada."
  }
}
