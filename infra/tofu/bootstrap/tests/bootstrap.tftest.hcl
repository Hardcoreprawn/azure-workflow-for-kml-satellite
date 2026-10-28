mock_provider "azurerm" {
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
  mock_resource "azurerm_key_vault" {
    defaults = {
      id        = "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-kmlsat-dev-bootstrap/providers/Microsoft.KeyVault/vaults/bootstrap-dev"
      vault_uri = "https://bootstrap-dev.vault.azure.net/"
    }
  }
  mock_resource "azurerm_key_vault_key" {
    defaults = {
      versionless_id          = "https://bootstrap-dev.vault.azure.net/keys/bootstrap-state"
      resource_versionless_id = "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-kmlsat-dev-bootstrap/providers/Microsoft.KeyVault/vaults/bootstrap-dev/keys/bootstrap-state"
    }
  }
  mock_resource "azurerm_user_assigned_identity" {
    defaults = {
      id           = "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-kmlsat-dev-bootstrap/providers/Microsoft.ManagedIdentity/userAssignedIdentities/state-encryption"
      principal_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    }
  }
  mock_resource "azurerm_storage_account" {
    defaults = {
      id = "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-kmlsat-dev-bootstrap/providers/Microsoft.Storage/storageAccounts/stkmlsatdevbootstrap"
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
    id = "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-kmlsat-dev-bootstrap/providers/Microsoft.Storage/storageAccounts/stkmlsatdevbootstrap/blobServices/default/containers/foundation"
  }
}

override_resource {
  target = azurerm_storage_container.state["workload"]
  values = {
    id = "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-kmlsat-dev-bootstrap/providers/Microsoft.Storage/storageAccounts/stkmlsatdevbootstrap/blobServices/default/containers/workload"
  }
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

variables {
  environment                  = "dev"
  location                     = "westeurope"
  subscription_id              = "11111111-1111-4111-8111-111111111111"
  tenant_id                    = "22222222-2222-4222-8222-222222222222"
  project_code                 = "kmlsat"
  bootstrap_phase              = "state"
  bootstrap_operator_object_id = "99999999-9999-4999-8999-999999999999"
  state_key_expiration_date    = "2030-01-01T00:00:00Z"
  bootstrap_allowed_ip_ranges  = ["203.0.113.10"]
}

run "rotation_owns_expiry_lifecycle" {
  command = plan

  assert {
    condition     = can(regex("ignore_changes\\s*=\\s*\\[expiration_date\\]", file("${path.module}/main.tf")))
    error_message = "Rotation must own subsequent expiry instead of each plan overwriting it."
  }
  assert {
    condition     = !strcontains(file("${path.module}/variables.tf"), "plantimestamp()")
    error_message = "The original expiry input must not age out; validate the effective resource instead."
  }
}

run "short_future_initial_expiry_rotates_before_expiry" {
  command = plan

  variables {
    state_key_expiration_date = timeadd(plantimestamp(), "1440h")
  }

  assert {
    condition = (
      timecmp(azurerm_key_vault_key.state[0].expiration_date, plantimestamp()) > 0 &&
      azurerm_key_vault_key.state[0].rotation_policy[0].automatic[0].time_before_expiry == "P90D"
    )
    error_message = "A short-future initial expiry must use expiry-relative rotation with enough overlap for adoption."
  }
}

run "trust_is_closed_by_default" {
  command = plan

  assert {
    condition = (
      azurerm_log_analytics_workspace.audit.local_authentication_disabled &&
      !azurerm_log_analytics_workspace.audit.allow_resource_only_permissions &&
      azurerm_log_analytics_workspace.audit.retention_in_days == 30 &&
      azurerm_monitor_diagnostic_setting.vault.target_resource_id == azurerm_key_vault.state.id &&
      azurerm_monitor_diagnostic_setting.vault.log_analytics_workspace_id == azurerm_log_analytics_workspace.audit.id &&
      toset([for log in azurerm_monitor_diagnostic_setting.vault.enabled_log : log.category]) == toset(["AuditEvent"]) &&
      azurerm_monitor_diagnostic_setting.state[0].target_resource_id == "${azurerm_storage_account.state[0].id}/blobServices/default" &&
      azurerm_monitor_diagnostic_setting.state[0].log_analytics_workspace_id == azurerm_log_analytics_workspace.audit.id &&
      toset([for log in azurerm_monitor_diagnostic_setting.state[0].enabled_log : log.category]) == toset(["StorageRead", "StorageWrite", "StorageDelete"])
    )
    error_message = "Audit all state blob operations and key access in a separate Entra-only bootstrap workspace."
  }

  assert {
    condition     = length(azurerm_federated_identity_credential.github) == 0
    error_message = "Bootstrap must not establish GitHub trust before owner activation."
  }

  assert {
    condition = (
      toset(keys(azurerm_user_assigned_identity.deployment)) == toset(["foundation", "workload", "release"]) &&
      toset(keys(azurerm_role_assignment.state)) == toset(["foundation", "workload"]) &&
      length(distinct([for identity in azurerm_user_assigned_identity.deployment : identity.principal_id])) == 3
    )
    error_message = "Each layer needs a separate identity; release must have no state grant."
  }

  assert {
    condition = alltrue([
      for layer, grant in azurerm_role_assignment.state :
      grant.role_definition_name == "Storage Blob Data Contributor" &&
      grant.scope == azurerm_storage_container.state[layer].id &&
      grant.principal_id == azurerm_user_assigned_identity.deployment[layer].principal_id
    ])
    error_message = "State grants must target only the matching layer's container and identity."
  }

  assert {
    condition = (
      !azurerm_storage_account.state[0].shared_access_key_enabled &&
      !azurerm_storage_account.state[0].allow_nested_items_to_be_public &&
      azurerm_storage_account.state[0].default_to_oauth_authentication &&
      azurerm_storage_account.state[0].min_tls_version == "TLS1_2" &&
      alltrue([for container in azurerm_storage_container.state : container.container_access_type == "private"])
    )
    error_message = "State must require Entra authentication and TLS, with no public blobs or shared-key bypass."
  }

  assert {
    condition = (
      azurerm_storage_account.state[0].infrastructure_encryption_enabled &&
      azurerm_storage_account.state[0].customer_managed_key[0].key_vault_key_id == azurerm_key_vault_key.state[0].versionless_id &&
      azurerm_storage_account.state[0].customer_managed_key[0].user_assigned_identity_id == azurerm_user_assigned_identity.storage_encryption.id &&
      azurerm_key_vault.state.purge_protection_enabled &&
      azurerm_key_vault.state.enable_rbac_authorization &&
      azurerm_key_vault.state.soft_delete_retention_days == 90 &&
      azurerm_key_vault_key.state[0].rotation_policy[0].automatic[0].time_before_expiry == "P90D"
    )
    error_message = "Bootstrap state must use both infrastructure encryption and a customer-managed key."
  }

  assert {
    condition = (
      azurerm_storage_account.state[0].blob_properties[0].versioning_enabled &&
      azurerm_storage_account.state[0].blob_properties[0].delete_retention_policy[0].days == 30 &&
      azurerm_storage_account.state[0].blob_properties[0].container_delete_retention_policy[0].days == 30
    )
    error_message = "State versions and deleted blobs/containers need a recovery window."
  }

  assert {
    condition = (
      output.bootstrap_contract.schema_version == 1 &&
      output.bootstrap_contract.environment == "dev" &&
      output.bootstrap_contract.oidc_enabled == false &&
      toset(keys(output.bootstrap_contract)) == toset([
        "schema_version", "phase", "environment", "tenant_id", "subscription_id", "oidc_enabled", "identities", "backends", "encryption"
      ]) &&
      toset(keys(output.bootstrap_contract.backends)) == toset(["foundation", "workload"])
    )
    error_message = "Publish only the versioned allowlisted bootstrap contract, not raw state."
  }

  assert {
    condition = (
      output.bootstrap_contract.phase == "state" &&
      toset(keys(output.bootstrap_contract.encryption)) == toset(["vault_uri", "storage_identity_id", "key_uri"]) &&
      azurerm_role_assignment.key_custodian.scope == azurerm_key_vault.state.id &&
      azurerm_role_assignment.key_custodian.role_definition_name == "Key Vault Crypto Officer" &&
      azurerm_role_assignment.storage_encryption[0].scope == azurerm_key_vault_key.state[0].resource_versionless_id &&
      azurerm_role_assignment.storage_encryption[0].role_definition_name == "Key Vault Crypto Service Encryption User" &&
      azurerm_role_assignment.storage_encryption[0].principal_id == azurerm_user_assigned_identity.storage_encryption.principal_id &&
      !contains([for identity in azurerm_user_assigned_identity.deployment : identity.principal_id], azurerm_role_assignment.key_custodian.principal_id) &&
      !contains([for identity in azurerm_user_assigned_identity.deployment : identity.principal_id], azurerm_role_assignment.storage_encryption[0].principal_id)
    )
    error_message = "Key custody and key-scoped encryption access must stay separate from every deployment identity."
  }

  assert {
    condition = (
      azurerm_key_vault.state.network_acls[0].default_action == "Deny" &&
      azurerm_key_vault.state.network_acls[0].bypass == "AzureServices" &&
      toset(azurerm_key_vault.state.network_acls[0].ip_rules) == toset(var.bootstrap_allowed_ip_ranges) &&
      azurerm_storage_account.state[0].network_rules[0].default_action == "Deny" &&
      toset(azurerm_storage_account.state[0].network_rules[0].bypass) == toset(["None"]) &&
      toset(azurerm_storage_account.state[0].network_rules[0].ip_rules) == toset(var.bootstrap_allowed_ip_ranges)
    )
    error_message = "Data endpoints must reject unapproved network sources as well as unauthorized identities."
  }

  assert {
    condition = alltrue([
      for layer, backend in output.bootstrap_contract.backends :
      backend.use_oidc && backend.use_azuread_auth && !backend.use_cli &&
      backend.key == "terraform.tfstate" &&
      backend.container_name == layer &&
      backend.client_id == azurerm_user_assigned_identity.deployment[layer].client_id &&
      backend.tenant_id == var.tenant_id && backend.subscription_id == var.subscription_id &&
      toset(keys(backend)) == toset([
        "resource_group_name", "storage_account_name", "container_name", "key",
        "use_oidc", "use_azuread_auth", "use_cli", "client_id", "tenant_id", "subscription_id"
      ])
    ])
    error_message = "Each backend must select its own identity and Entra/OIDC without keys or CLI fallback."
  }

  assert {
    condition = alltrue([
      for layer, identity in output.bootstrap_contract.identities :
      identity.github_environment == "dev-${layer}" &&
      toset(keys(identity)) == toset(["resource_id", "client_id", "principal_id", "github_environment"])
    ])
    error_message = "Identity handoffs must expose only identifiers and layer-specific environment names."
  }
}

run "explicit_oidc_activation_keeps_layers_separate" {
  command = plan

  variables {
    enable_github_oidc = true
  }

  assert {
    condition = (
      length(azurerm_federated_identity_credential.github) == 3 &&
      length(distinct([for credential in azurerm_federated_identity_credential.github : credential.subject])) == 3 &&
      alltrue([
        for layer, credential in azurerm_federated_identity_credential.github :
        credential.subject == "repo:Hardcoreprawn/azure-workflow-for-kml-satellite:environment:dev-${layer}" &&
        credential.issuer == "https://token.actions.githubusercontent.com" &&
        toset(credential.audience) == toset(["api://AzureADTokenExchange"]) &&
        credential.parent_id == azurerm_user_assigned_identity.deployment[layer].id
      ])
    )
    error_message = "Trust must bind this repository, exact environment/layer, identity and Azure audience."
  }
}

run "identity_phase_does_not_create_key_or_state" {
  command = plan

  variables {
    bootstrap_phase             = "identity"
    state_key_expiration_date   = null
    bootstrap_allowed_ip_ranges = []
  }

  assert {
    condition = (
      length(azurerm_key_vault_key.state) == 0 &&
      length(azurerm_role_assignment.storage_encryption) == 0 &&
      length(azurerm_storage_account.state) == 0 &&
      length(azurerm_storage_container.state) == 0 &&
      length(azurerm_role_assignment.state) == 0 &&
      length(azurerm_federated_identity_credential.github) == 0 &&
      output.bootstrap_contract.phase == "identity" &&
      output.bootstrap_contract.encryption.key_uri == null &&
      length(output.bootstrap_contract.backends) == 0
    )
    error_message = "The initial phase must allow key-custodian propagation verification before dependent resources exist."
  }
}

run "key_phase_does_not_create_state_or_trust" {
  command = plan

  variables {
    bootstrap_phase = "key"
  }

  assert {
    condition = (
      length(azurerm_key_vault_key.state) == 1 &&
      length(azurerm_role_assignment.storage_encryption) == 1 &&
      length(azurerm_storage_account.state) == 0 &&
      length(azurerm_role_assignment.state) == 0 &&
      length(azurerm_federated_identity_credential.github) == 0 &&
      output.bootstrap_contract.phase == "key" &&
      length(output.bootstrap_contract.backends) == 0
    )
    error_message = "The key phase must permit verification of the encryption grant before storage is created."
  }
}
