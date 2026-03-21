terraform {
  required_version = ">= 1.6.0" # OpenTofu compatible

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
  }

  backend "azurerm" {
    resource_group_name  = "treesight-tfstate"
    storage_account_name = "treesighttfstate"
    container_name       = "tfstate"
    key                  = "treesight.tfstate"
  }
}

provider "azurerm" {
  features {}
  subscription_id = var.subscription_id
}
