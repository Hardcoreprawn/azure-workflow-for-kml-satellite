mock_provider "azurerm" {
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
  environment     = "dev"
  location        = "westeurope"
  subscription_id = "11111111-1111-4111-8111-111111111111"
  tenant_id       = "22222222-2222-4222-8222-222222222222"
  project_code    = "kmlsat"
}

run "trust_is_closed_by_default" {
  command = plan

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
      !azurerm_storage_account.state.shared_access_key_enabled &&
      !azurerm_storage_account.state.allow_nested_items_to_be_public &&
      azurerm_storage_account.state.default_to_oauth_authentication &&
      azurerm_storage_account.state.min_tls_version == "TLS1_2" &&
      alltrue([for container in azurerm_storage_container.state : container.container_access_type == "private"])
    )
    error_message = "State must require Entra authentication and TLS, with no public blobs or shared-key bypass."
  }

  assert {
    condition = (
      azurerm_storage_account.state.blob_properties[0].versioning_enabled &&
      azurerm_storage_account.state.blob_properties[0].delete_retention_policy[0].days == 30 &&
      azurerm_storage_account.state.blob_properties[0].container_delete_retention_policy[0].days == 30
    )
    error_message = "State versions and deleted blobs/containers need a recovery window."
  }

  assert {
    condition = (
      output.bootstrap_contract.schema_version == 1 &&
      output.bootstrap_contract.environment == "dev" &&
      output.bootstrap_contract.oidc_enabled == false &&
      toset(keys(output.bootstrap_contract)) == toset([
        "schema_version", "environment", "tenant_id", "subscription_id", "oidc_enabled", "identities", "backends"
      ]) &&
      toset(keys(output.bootstrap_contract.backends)) == toset(["foundation", "workload"])
    )
    error_message = "Publish only the versioned allowlisted bootstrap contract, not raw state."
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
