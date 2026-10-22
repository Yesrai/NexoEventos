terraform {
  required_version = ">= 1.16.0, < 2.0.0"
  # Estado SEPARADO (OCI): terraform init -backend-config="path=$PWD/../../work/terraform-state/oci/terraform.tfstate". Nunca en Git.
  backend "local" {}
  required_providers {
    oci = {
      source  = "oracle/oci"
      version = "= 9.11.0"
    }
  }
}

# Autenticación fuera del repositorio: archivo ~/.oci/config (clave API del usuario) o variables de entorno OCI_*; nada de esto va en Git.
provider "oci" {
  region              = var.region
  config_file_profile = var.config_file_profile
}
