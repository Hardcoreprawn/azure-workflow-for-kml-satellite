mock_provider "azurerm" {
  mock_resource "azurerm_resource_group" {
    defaults = {
      id = "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-kmlsat-dev-bootstrap"
    }
  }
  mock_resource "azurerm_key_vault" {
    defaults = {
      id        = "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-kmlsat-dev-bootstrap/providers/Microsoft.KeyVault/vaults/kkmlsatdevvabc123"
      vault_uri = "https://kkmlsatdevvabc123.vault.azure.net/"
    }
  }
  mock_resource "azurerm_key_vault_key" {
    defaults = {
      versionless_id          = "https://kkmlsatdevvabc123.vault.azure.net/keys/bootstrap-state"
      resource_versionless_id = "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-kmlsat-dev-bootstrap/providers/Microsoft.KeyVault/vaults/kkmlsatdevvabc123/keys/bootstrap-state"
    }
  }
  mock_resource "azurerm_log_analytics_workspace" {
    defaults = {
      id = "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-kmlsat-dev-bootstrap/providers/Microsoft.OperationalInsights/workspaces/law-kmlsat-dev-bootstrap"
    }
  }
  mock_resource "azurerm_storage_account" {
    defaults = {
      id = "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-kmlsat-dev-bootstrap/providers/Microsoft.Storage/storageAccounts/kmlsatdevtfabc123"
    }
  }
  mock_resource "azurerm_user_assigned_identity" {
    defaults = {
      id           = "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-kmlsat-dev-bootstrap/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-kmlsat-dev-state-encryption"
      principal_id = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
    }
  }
  mock_data "azurerm_client_config" {
    defaults = {
      object_id = "99999999-9999-4999-8999-999999999999"
    }
  }
}

mock_provider "random" {
  mock_resource "random_string" {
    defaults = { result = "abc123" }
  }
}

mock_provider "azurerm" {
  alias = "application"
}

override_resource {
  target = azurerm_user_assigned_identity.deployment["foundation"]
  values = {
    id           = "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-kmlsat-dev-bootstrap/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-kmlsat-dev-foundation"
    client_id    = "33333333-3333-4333-8333-333333333333"
    principal_id = "44444444-4444-4444-8444-444444444444"
  }
}

override_resource {
  target = azurerm_user_assigned_identity.deployment["workload"]
  values = {
    id           = "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-kmlsat-dev-bootstrap/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-kmlsat-dev-workload"
    client_id    = "55555555-5555-4555-8555-555555555555"
    principal_id = "66666666-6666-4666-8666-666666666666"
  }
}

override_resource {
  target = azurerm_user_assigned_identity.deployment["release"]
  values = {
    id           = "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-kmlsat-dev-bootstrap/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-kmlsat-dev-release"
    client_id    = "77777777-7777-4777-8777-777777777777"
    principal_id = "88888888-8888-4888-8888-888888888888"
  }
}

override_resource {
  target = azurerm_resource_group.application[0]
  values = {
    id = "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-kmlsat-dev-application"
  }
}

override_resource {
  target = azurerm_key_vault.application[0]
  values = {
    id        = "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-kmlsat-dev-application/providers/Microsoft.KeyVault/vaults/akmlsatdevvabc123"
    vault_uri = "https://akmlsatdevvabc123.vault.azure.net/"
  }
}

override_resource {
  target = azurerm_role_definition.application_foundation[0]
  values = {
    role_definition_resource_id = "/subscriptions/11111111-1111-4111-8111-111111111111/providers/Microsoft.Authorization/roleDefinitions/c4b75064-8c04-599a-a420-32f2ed4629be"
  }
}

override_resource {
  target = azurerm_storage_container.state["foundation"]
  values = {
    id = "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-kmlsat-dev-bootstrap/providers/Microsoft.Storage/storageAccounts/kmlsatdevtfabc123/blobServices/default/containers/foundation"
  }
}

override_resource {
  target = azurerm_storage_container.state["workload"]
  values = {
    id = "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-kmlsat-dev-bootstrap/providers/Microsoft.Storage/storageAccounts/kmlsatdevtfabc123/blobServices/default/containers/workload"
  }
}

variables {
  environment                   = "dev"
  location                      = "westeurope"
  subscription_id               = "11111111-1111-4111-8111-111111111111"
  tenant_id                     = "22222222-2222-4222-8222-222222222222"
  bootstrap_operator_object_id  = "99999999-9999-4999-8999-999999999999"
  bootstrap_phase               = "state"
  bootstrap_allowed_ip_ranges   = ["203.0.113.10"]
  application_allowed_ip_ranges = ["203.0.113.10"]
  application_phase             = "namespace"
  application_bootstrap_json    = file("../../../tests/fixtures/application_governance/bootstrap.json")
  application_bootstrap_sha256  = filesha256("../../../tests/fixtures/application_governance/bootstrap.json")
  application_revisions = {
    governance = "1111111111111111111111111111111111111111"
    foundation = "2222222222222222222222222222222222222222"
    policy     = "3333333333333333333333333333333333333333"
  }
}

run "namespace_and_vault_are_governance_owned" {
  command = plan

  assert {
    condition = (
      azurerm_resource_group.application[0].name == "rg-kmlsat-dev-application" &&
      azurerm_resource_group.application[0].id != azurerm_resource_group.bootstrap.id &&
      azurerm_key_vault.application[0].resource_group_name == azurerm_resource_group.application[0].name &&
      azurerm_key_vault.application[0].enable_rbac_authorization &&
      azurerm_key_vault.application[0].purge_protection_enabled &&
      azurerm_key_vault.application[0].soft_delete_retention_days == 90 &&
      azurerm_key_vault.application[0].network_acls[0].default_action == "Deny" &&
      azurerm_key_vault.application[0].network_acls[0].ip_rules == toset(["203.0.113.10"])
    )
    error_message = "Governance alone owns the fresh isolated RBAC vault and namespace with approved network/recovery."
  }
  assert {
    condition = (
      azurerm_role_assignment.application_foundation[0].scope == azurerm_resource_group.application[0].id &&
      azurerm_role_assignment.application_foundation[0].principal_id == azurerm_user_assigned_identity.deployment["foundation"].principal_id &&
      azurerm_role_definition.application_foundation[0].scope == azurerm_resource_group.application[0].id &&
      toset(azurerm_role_definition.application_foundation[0].assignable_scopes) == toset([azurerm_resource_group.application[0].id]) &&
      length(azurerm_role_definition.application_foundation[0].permissions[0].data_actions) == 0 &&
      length(azurerm_role_definition.application_foundation[0].permissions[0].not_actions) == 0 &&
      length(azurerm_role_assignment.application_custody) == 0 &&
      length(azurerm_role_assignment.application_encryption) == 0
    )
    error_message = "Foundation authority must be app-RG scoped and must not grant key custody before prerequisites."
  }
  assert {
    condition = alltrue([
      for action in azurerm_role_definition.application_foundation[0].permissions[0].actions :
      !strcontains(action, "*") &&
      !startswith(lower(action), "microsoft.authorization/") &&
      (!startswith(lower(action), "microsoft.keyvault/") || lower(action) == "microsoft.keyvault/vaults/read") &&
      (!startswith(lower(action), "microsoft.resources/") || lower(action) == "microsoft.resources/subscriptions/resourcegroups/read") &&
      !strcontains(lower(action), "federated") &&
      !strcontains(lower(action), "listkeys") &&
      !strcontains(lower(action), "sharedkeys")
    ])
    error_message = "The allowlist must exclude namespace mutation, vault lifecycle/access policies, IAM/trust and key retrieval."
  }

  assert {
    condition = (
      output.application_contract.stage == "namespace" &&
      output.application_contract.status == "declared-not-activated" &&
      output.application_contract.payload.vault_id == azurerm_key_vault.application[0].id &&
      output.application_contract.payload.foundation_role_definition_id == azurerm_role_definition.application_foundation[0].role_definition_resource_id &&
      jsondecode(output.application_contract_json) == output.application_contract
    )
    error_message = "Namespace artifact must refer to the governance vault without fabricating later resources/readiness."
  }
}

run "custody_follows_foundation_prerequisites" {
  command = plan
  variables {
    application_phase = "custody"
    application_artifacts = [
      file("../../../tests/fixtures/application_governance/namespace.json"),
      file("../../../tests/fixtures/application_governance/prerequisites.json"),
    ]
  }
  assert {
    condition = (
      azurerm_role_assignment.application_custody[0].scope == azurerm_key_vault.application[0].id &&
      azurerm_role_assignment.application_custody[0].principal_id == azurerm_user_assigned_identity.deployment["foundation"].principal_id &&
      endswith(azurerm_role_assignment.application_custody[0].role_definition_id, "/14b46e9e-c2b7-41b4-b07b-48a6ebf60603") &&
      length(azurerm_role_assignment.application_encryption) == 0 &&
      output.application_contract.stage == "custody"
    )
    error_message = "Only governance grants foundation vault-scoped Crypto Officer after the validated intermediate artifact."
  }
}

run "encryption_follows_custody_and_foundation_key" {
  command = plan
  variables {
    application_phase = "encryption"
    application_artifacts = [
      file("../../../tests/fixtures/application_governance/namespace.json"),
      file("../../../tests/fixtures/application_governance/prerequisites.json"),
      file("../../../tests/fixtures/application_governance/custody.json"),
      file("../../../tests/fixtures/application_governance/key.json"),
    ]
  }
  assert {
    condition = (
      azurerm_role_assignment.application_encryption[0].scope == "${azurerm_key_vault.application[0].id}/keys/application-cmk" &&
      azurerm_role_assignment.application_encryption[0].principal_id == "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb" &&
      endswith(azurerm_role_assignment.application_encryption[0].role_definition_id, "/e147488a-f6f5-4113-8e2d-b22465e65bf6") &&
      output.application_contract.stage == "encryption" &&
      output.application_contract.status == "declared-not-activated"
    )
    error_message = "Encryption is key scoped to the dedicated service identity, not a deployment or upstream identity."
  }
}

run "reject_missing_custody_prerequisites" {
  command = plan
  variables {
    application_phase = "custody"
  }
  expect_failures = [var.application_artifacts]
}

run "cosmos_grant_preserves_blob_and_custody" {
  command = plan
  variables {
    application_phase = "cosmos-encryption"
    application_artifacts = [
      file("../../../tests/fixtures/application_governance/namespace.json"),
      file("../../../tests/fixtures/application_governance/prerequisites.json"),
      file("../../../tests/fixtures/application_governance/custody.json"),
      file("../../../tests/fixtures/application_governance/key.json"),
      file("../../../tests/fixtures/application_governance/encryption.json"),
      file("../../../tests/fixtures/application_governance/cosmos-key.json"),
    ]
  }
  assert {
    condition = (
      length(azurerm_role_assignment.application_foundation) == 1 &&
      length(azurerm_role_assignment.application_custody) == 1 &&
      azurerm_role_assignment.application_encryption[0].scope == "${azurerm_key_vault.application[0].id}/keys/application-cmk" &&
      azurerm_role_assignment.application_encryption[0].principal_id == "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb" &&
      azurerm_role_assignment.application_cosmos_encryption[0].scope == "${azurerm_key_vault.application[0].id}/keys/cosmos-cmk" &&
      azurerm_role_assignment.application_cosmos_encryption[0].principal_id == "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee" &&
      endswith(azurerm_role_assignment.application_cosmos_encryption[0].role_definition_id, "/e147488a-f6f5-4113-8e2d-b22465e65bf6") &&
      output.application_contract.stage == "cosmos-encryption" &&
      output.application_contract.schema_version == 2 &&
      output.bootstrap_contract.schema_version == 1
    )
    error_message = "Cosmos grant must be key scoped and dedicated, preserving every earlier grant and bootstrap v1."
  }
  assert {
    condition = alltrue([
      for action in azurerm_role_definition.application_foundation[0].permissions[0].actions :
      !strcontains(lower(action), "listkeys") &&
      !strcontains(lower(action), "readonlykeys") &&
      !strcontains(lower(action), "connectionstrings") &&
      !strcontains(lower(action), "restore") &&
      !strcontains(lower(action), "sqlrole") &&
      !strcontains(action, "*")
    ])
    error_message = "Foundation must not gain credentials, restore, data grants or wildcard permissions."
  }
}

run "reject_missing_cosmos_key_before_grant" {
  command = plan
  variables { application_phase = "cosmos-encryption" }
  expect_failures = [var.application_artifacts]
}

run "reject_missing_key_before_encryption" {
  command = plan
  variables {
    application_phase = "encryption"
    application_artifacts = [
      file("../../../tests/fixtures/application_governance/namespace.json"),
      file("../../../tests/fixtures/application_governance/prerequisites.json"),
    ]
  }
  expect_failures = [var.application_artifacts]
}

run "reject_unapproved_application_network" {
  command = plan
  variables {
    application_allowed_ip_ranges = ["0.0.0.0/0"]
  }
  expect_failures = [var.application_allowed_ip_ranges]
}

run "uuid_case_does_not_change_authorized_custodian_or_role_seed" {
  command = plan
  variables {
    application_phase            = "disabled"
    subscription_id              = "ABCDEFAB-CDEF-4ABC-8DEF-ABCDEFABCDEF"
    bootstrap_operator_object_id = "AbCdEfAb-CdEf-4aBc-8dEf-AbCdEfAbCdEf"
  }
  override_data {
    target = data.azurerm_client_config.operator
    values = { object_id = "abcdefab-cdef-4abc-8def-abcdefabcdef" }
  }
  assert {
    condition     = local.application_role_uuid == uuidv5("url", "canopex/abcdefab-cdef-4abc-8def-abcdefabcdef/dev/foundation-application")
    error_message = "The same subscription UUID must always derive the same role UUID, irrespective of case."
  }
}

run "uuid_case_cannot_alias_storage_encryption_as_custodian" {
  command = plan
  variables {
    application_phase            = "disabled"
    bootstrap_operator_object_id = "CCCCCCCC-CCCC-4CCC-8CCC-CCCCCCCCCCCC"
  }
  override_data {
    target = data.azurerm_client_config.operator
    values = { object_id = "cccccccc-cccc-4ccc-8ccc-cccccccccccc" }
  }
  expect_failures = [azurerm_role_assignment.key_custodian]
}
