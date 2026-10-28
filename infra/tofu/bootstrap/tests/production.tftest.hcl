mock_provider "azurerm" {
  mock_resource "azurerm_storage_account" {
    defaults = {
      id = "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-kmlsat-prd-bootstrap/providers/Microsoft.Storage/storageAccounts/stkmlsatprdbootstrap"
    }
  }
  mock_resource "azurerm_storage_container" {
    defaults = {
      id = "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-kmlsat-prd-bootstrap/providers/Microsoft.Storage/storageAccounts/stkmlsatprdbootstrap/blobServices/default/containers/mock"
    }
  }
  mock_resource "azurerm_user_assigned_identity" {
    defaults = {
      id           = "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-kmlsat-prd-bootstrap/providers/Microsoft.ManagedIdentity/userAssignedIdentities/mock"
      principal_id = "33333333-3333-4333-8333-333333333333"
    }
  }
}
mock_provider "random" {
  mock_resource "random_string" {
    defaults = {
      result = "abc123"
    }
  }
}

variables {
  environment        = "prd"
  location           = "westeurope"
  subscription_id    = "11111111-1111-4111-8111-111111111111"
  tenant_id          = "22222222-2222-4222-8222-222222222222"
  project_code       = "kmlsat"
  enable_github_oidc = true
}

run "production_has_its_own_namespace_and_trust" {
  command = plan

  assert {
    condition = (
      azurerm_resource_group.bootstrap.name == "rg-kmlsat-prd-bootstrap" &&
      alltrue([
        for layer, credential in azurerm_federated_identity_credential.github :
        credential.subject == "repo:Hardcoreprawn/azure-workflow-for-kml-satellite:environment:prd-${layer}"
      ]) &&
      alltrue([
        for layer, identity in azurerm_user_assigned_identity.deployment :
        identity.name == "id-kmlsat-prd-${layer}"
      ])
    )
    error_message = "Production state and trust must not reuse development names or subjects."
  }
}
