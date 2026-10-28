mock_provider "azurerm" {
  mock_resource "azurerm_storage_account" {
    defaults = {
      id = "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-kmlsat-prd-bootstrap/providers/Microsoft.Storage/storageAccounts/stkmlsatprdbootstrap"
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

override_resource {
  target = azurerm_storage_container.state["foundation"]
  values = {
    id = "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-kmlsat-prd-bootstrap/providers/Microsoft.Storage/storageAccounts/stkmlsatprdbootstrap/blobServices/default/containers/foundation"
  }
}

override_resource {
  target = azurerm_storage_container.state["workload"]
  values = {
    id = "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-kmlsat-prd-bootstrap/providers/Microsoft.Storage/storageAccounts/stkmlsatprdbootstrap/blobServices/default/containers/workload"
  }
}

override_resource {
  target = azurerm_user_assigned_identity.deployment["foundation"]
  values = {
    id           = "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-kmlsat-prd-bootstrap/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-kmlsat-prd-foundation"
    client_id    = "33333333-3333-4333-8333-333333333333"
    principal_id = "44444444-4444-4444-8444-444444444444"
  }
}

override_resource {
  target = azurerm_user_assigned_identity.deployment["workload"]
  values = {
    id           = "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-kmlsat-prd-bootstrap/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-kmlsat-prd-workload"
    client_id    = "55555555-5555-4555-8555-555555555555"
    principal_id = "66666666-6666-4666-8666-666666666666"
  }
}

override_resource {
  target = azurerm_user_assigned_identity.deployment["release"]
  values = {
    id           = "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-kmlsat-prd-bootstrap/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-kmlsat-prd-release"
    client_id    = "77777777-7777-4777-8777-777777777777"
    principal_id = "88888888-8888-4888-8888-888888888888"
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

  assert {
    condition = (
      length(distinct([for identity in azurerm_user_assigned_identity.deployment : identity.principal_id])) == 3 &&
      toset(keys(azurerm_role_assignment.state)) == toset(["foundation", "workload"]) &&
      toset(keys(output.bootstrap_contract.backends)) == toset(["foundation", "workload"]) &&
      alltrue([
        for layer, grant in azurerm_role_assignment.state :
        grant.scope == azurerm_storage_container.state[layer].id &&
        grant.principal_id == azurerm_user_assigned_identity.deployment[layer].principal_id &&
        grant.role_definition_name == "Storage Blob Data Contributor" &&
        output.bootstrap_contract.backends[layer].client_id == azurerm_user_assigned_identity.deployment[layer].client_id &&
        output.bootstrap_contract.backends[layer].container_name == layer
      ])
    )
    error_message = "Production grants and backend identities must retain the same per-layer isolation as DEV."
  }
}
