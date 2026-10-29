mock_provider "azurerm" {
  mock_resource "azurerm_log_analytics_workspace" {
    defaults = {
      id = "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-kmlsat-prd-bootstrap/providers/Microsoft.OperationalInsights/workspaces/law-kmlsat-prd-bootstrap"
    }
  }
  mock_data "azurerm_client_config" {
    defaults = {
      object_id = "99999999-9999-4999-8999-999999999999"
    }
  }
  mock_resource "azurerm_key_vault" {
    defaults = {
      id        = "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-kmlsat-prd-bootstrap/providers/Microsoft.KeyVault/vaults/bootstrap-prd"
      vault_uri = "https://bootstrap-prd.vault.azure.net/"
    }
  }
  mock_resource "azurerm_key_vault_key" {
    defaults = {
      versionless_id          = "https://bootstrap-prd.vault.azure.net/keys/bootstrap-state"
      resource_versionless_id = "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-kmlsat-prd-bootstrap/providers/Microsoft.KeyVault/vaults/bootstrap-prd/keys/bootstrap-state"
    }
  }
  mock_resource "azurerm_user_assigned_identity" {
    defaults = {
      id           = "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-kmlsat-prd-bootstrap/providers/Microsoft.ManagedIdentity/userAssignedIdentities/state-encryption"
      principal_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    }
  }
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

mock_provider "azurerm" {
  alias = "application"
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
    client_id    = "13131313-1313-4131-8131-131313131313"
    principal_id = "14141414-1414-4141-8141-141414141414"
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
  environment                  = "prd"
  location                     = "westeurope"
  subscription_id              = "11111111-1111-4111-8111-111111111111"
  tenant_id                    = "22222222-2222-4222-8222-222222222222"
  project_code                 = "kmlsat"
  enable_github_oidc           = true
  bootstrap_phase              = "state"
  bootstrap_operator_object_id = "99999999-9999-4999-8999-999999999999"
  bootstrap_allowed_ip_ranges  = ["203.0.113.10"]
}

run "production_has_its_own_namespace_and_trust" {
  command = plan

  assert {
    condition = (
      azurerm_log_analytics_workspace.audit.name == "law-kmlsat-prd-bootstrap" &&
      azurerm_monitor_diagnostic_setting.vault.log_analytics_workspace_id == azurerm_log_analytics_workspace.audit.id &&
      azurerm_monitor_diagnostic_setting.state[0].log_analytics_workspace_id == azurerm_log_analytics_workspace.audit.id
    )
    error_message = "Production bootstrap must not send state/key audit logs into a DEV workspace."
  }

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

run "production_application_vault_and_authority_are_not_dev" {
  command = plan
  variables {
    application_phase             = "namespace"
    application_allowed_ip_ranges = ["203.0.113.10"]
    application_bootstrap_json    = file("../../../tests/fixtures/application_governance/production-bootstrap.json")
    application_bootstrap_sha256  = filesha256("../../../tests/fixtures/application_governance/production-bootstrap.json")
    application_revisions = {
      governance = "1111111111111111111111111111111111111111"
      foundation = "2222222222222222222222222222222222222222"
      policy     = "3333333333333333333333333333333333333333"
    }
  }
  override_resource {
    target = azurerm_user_assigned_identity.storage_encryption
    values = {
      id           = "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-kmlsat-prd-bootstrap/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-kmlsat-prd-state-encryption"
      principal_id = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
    }
  }
  override_resource {
    target = azurerm_resource_group.application[0]
    values = {
      id = "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-kmlsat-prd-application"
    }
  }
  override_resource {
    target = azurerm_key_vault.application[0]
    values = {
      id        = "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-kmlsat-prd-application/providers/Microsoft.KeyVault/vaults/akmlsatprdvabc123"
      vault_uri = "https://akmlsatprdvabc123.vault.azure.net/"
    }
  }
  override_resource {
    target = azurerm_role_definition.application_foundation[0]
    values = {
      role_definition_resource_id = "/subscriptions/11111111-1111-4111-8111-111111111111/providers/Microsoft.Authorization/roleDefinitions/67ac2670-3210-528b-8023-07ee3063ceec"
    }
  }
  assert {
    condition = (
      azurerm_resource_group.application[0].name == "rg-kmlsat-prd-application" &&
      azurerm_key_vault.application[0].name == "akmlsatprdvabc123" &&
      output.application_contract.environment == "prd" &&
      output.application_contract.payload.vault_id == azurerm_key_vault.application[0].id &&
      output.application_contract.payload.foundation_role_definition_id == azurerm_role_definition.application_foundation[0].role_definition_resource_id &&
      azurerm_role_assignment.application_foundation[0].scope == azurerm_resource_group.application[0].id &&
      azurerm_role_assignment.application_foundation[0].principal_id == "14141414-1414-4141-8141-141414141414" &&
      output.application_contract.backend.client_id == "13131313-1313-4131-8131-131313131313"
    )
    error_message = "Production must bind its own application namespace/vault, role and foundation principal/backend, never DEV."
  }
}
