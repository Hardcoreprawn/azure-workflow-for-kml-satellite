output "bootstrap_contract" {
  description = "Versioned, non-secret handoff only; consumers must not read this root's state."
  value = {
    schema_version  = 1
    environment     = var.environment
    tenant_id       = var.tenant_id
    subscription_id = var.subscription_id
    oidc_enabled    = var.enable_github_oidc
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
        storage_account_name = azurerm_storage_account.state.name
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
