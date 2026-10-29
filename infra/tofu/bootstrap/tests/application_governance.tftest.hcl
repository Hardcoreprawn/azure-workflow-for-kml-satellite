mock_provider "azurerm" {
  alias = "application"
}

mock_provider "azurerm" {
  mock_resource "azurerm_key_vault" {
    defaults = {
      id = "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-kmlsat-dev-bootstrap/providers/Microsoft.KeyVault/vaults/bootstrap-dev"
    }
  }
  mock_resource "azurerm_log_analytics_workspace" {
    defaults = {
      id = "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-kmlsat-dev-bootstrap/providers/Microsoft.OperationalInsights/workspaces/law-kmlsat-dev-bootstrap"
    }
  }
  mock_data "azurerm_client_config" {
    defaults = {
      object_id = "99999999-9999-4999-8999-999999999999"
    }
  }
}

mock_provider "random" {}

variables {
  environment                  = "dev"
  location                     = "westeurope"
  subscription_id              = "11111111-1111-4111-8111-111111111111"
  tenant_id                    = "22222222-2222-4222-8222-222222222222"
  bootstrap_operator_object_id = "99999999-9999-4999-8999-999999999999"
}

run "application_governance_defaults_closed" {
  command = plan

  assert {
    condition     = var.application_phase == "disabled" && length(azurerm_resource_group.application) == 0 && length(azurerm_key_vault.application) == 0 && output.application_contract == null
    error_message = "Application authority and resources must default closed."
  }
}

run "reject_application_before_bootstrap_state" {
  command = plan

  variables {
    application_phase = "namespace"
  }

  expect_failures = [var.application_phase]
}

run "reject_unknown_application_phase" {
  command = plan

  variables {
    environment       = "prd"
    application_phase = "storage"
  }

  expect_failures = [var.application_phase]
}
