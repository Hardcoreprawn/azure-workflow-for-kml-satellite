mock_provider "azurerm" {
  mock_resource "azurerm_storage_account" {
    defaults = {
      id = "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-kmlsat-dev-bootstrap/providers/Microsoft.Storage/storageAccounts/stkmlsatdevbootstrap"
    }
  }
  mock_resource "azurerm_storage_container" {
    defaults = {
      id = "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-kmlsat-dev-bootstrap/providers/Microsoft.Storage/storageAccounts/stkmlsatdevbootstrap/blobServices/default/containers/mock"
    }
  }
  mock_resource "azurerm_user_assigned_identity" {
    defaults = {
      principal_id = "33333333-3333-4333-8333-333333333333"
    }
  }
}
mock_provider "random" {}

variables {
  environment     = "dev"
  location        = "westeurope"
  subscription_id = "11111111-1111-4111-8111-111111111111"
  tenant_id       = "22222222-2222-4222-8222-222222222222"
  project_code    = "kmlsat"
}

run "reject_unknown_environment" {
  command = plan
  variables {
    environment = "preview"
  }
  expect_failures = [var.environment]
}

run "reject_invalid_project_name" {
  command = plan
  variables {
    project_code = "unsafe/name"
  }
  expect_failures = [var.project_code]
}

run "reject_invalid_subscription" {
  command = plan
  variables {
    subscription_id = "missing"
  }
  expect_failures = [var.subscription_id]
}

run "reject_invalid_tenant" {
  command = plan
  variables {
    tenant_id = "missing"
  }
  expect_failures = [var.tenant_id]
}

run "reject_missing_region" {
  command = plan
  variables {
    location = ""
  }
  expect_failures = [var.location]
}
