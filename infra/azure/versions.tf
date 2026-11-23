terraform {
  required_version = ">= 1.16.0, < 2.0.0"
  # Estado SEPARADO (Azure): terraform init -backend-config="path=$PWD/../../work/terraform-state/azure/terraform.tfstate". Nunca en Git.
  backend "local" {}
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "= 5.10.0"
    }
  }
}

# Autenticación fuera del repositorio: `az login` (sin service principal ni secretos en archivos).
# Los proveedores Microsoft.Compute/Network/Storage están NotRegistered: se registran a mano y con autorización, nunca automáticamente.
provider "azurerm" {
  features {
    # Al destruir, el espacio de Log Analytics se elimina de forma permanente (si no, queda 14 días en papelera y bloquea recrear el mismo nombre).
    log_analytics_workspace {
      permanently_delete_on_destroy = true
    }
  }
  subscription_id                 = var.subscription_id
  resource_provider_registrations = "none"
}
