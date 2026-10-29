terraform {
  required_version = ">= 1.13.2, < 2.0.0"

  required_providers {
    external = {
      source  = "hashicorp/external"
      version = "2.3.5"
    }
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "4.22.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "3.6.3"
    }
  }

  backend "local" {}
}
