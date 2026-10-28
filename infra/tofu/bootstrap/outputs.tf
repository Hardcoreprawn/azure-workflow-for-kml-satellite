output "bootstrap_contract" {
  description = "Versioned, non-secret handoff only; consumers must not read this root's state."
  value = {
    schema_version  = 1
    phase           = var.bootstrap_phase
    environment     = var.environment
    tenant_id       = var.tenant_id
    subscription_id = var.subscription_id
    oidc_enabled    = var.enable_github_oidc
    encryption = {
      vault_uri           = azurerm_key_vault.state.vault_uri
      storage_identity_id = azurerm_user_assigned_identity.storage_encryption.id
      key_uri             = local.key_enabled ? azurerm_key_vault_key.state[0].versionless_id : null
    }
    identities = {
      for layer, identity in azurerm_user_assigned_identity.deployment : layer => {
        resource_id        = identity.id
        client_id          = identity.client_id
        principal_id       = identity.principal_id
        github_environment = "${var.environment}-${layer}"
      }
    }
    backends = {
      for layer in local.state_layers : layer => {
        resource_group_name  = azurerm_resource_group.bootstrap.name
        storage_account_name = azurerm_storage_account.state[0].name
        container_name       = azurerm_storage_container.state[layer].name
        key                  = "terraform.tfstate"
        use_azuread_auth     = true
        use_oidc             = true
        use_cli              = false
        subscription_id      = var.subscription_id
        tenant_id            = var.tenant_id
        client_id            = azurerm_user_assigned_identity.deployment[layer].client_id
      }
    }
  }
}
