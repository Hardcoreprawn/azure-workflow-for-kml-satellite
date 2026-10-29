provider "azurerm" {
  alias = "application"
  features {
    key_vault {
      recover_soft_deleted_key_vaults = false
      purge_soft_delete_on_destroy    = false
    }
  }
  subscription_id                 = var.subscription_id
  tenant_id                       = var.tenant_id
  storage_use_azuread             = true
  resource_provider_registrations = "none"
}

locals {
  application_enabled        = contains(["namespace", "custody", "encryption"], var.application_phase) && var.bootstrap_phase == "state"
  application_namespace      = "rg-${local.name_suffix}-application"
  application_vault_name     = "a${var.project_code}${var.environment}v${random_string.storage_suffix.result}"
  application_actions        = jsondecode(file("${path.module}/../../contracts/application-governance/actions.json"))
  application_role_uuid      = uuidv5("url", "canopex/${var.subscription_id}/${var.environment}/foundation-application")
  application_custody_phases = local.application_enabled && contains(["custody", "encryption"], var.application_phase)
  application_context = local.application_enabled ? {
    environment                       = var.environment
    tenant_id                         = var.tenant_id
    subscription_id                   = var.subscription_id
    project_code                      = var.project_code
    location                          = var.location
    vault_name                        = local.application_vault_name
    governance_revision               = var.application_revisions.governance
    foundation_revision               = var.application_revisions.foundation
    policy_revision                   = var.application_revisions.policy
    bootstrap_sha256                  = var.application_bootstrap_sha256
    bootstrap_operator_principal_id   = var.bootstrap_operator_object_id
    bootstrap_encryption_principal_id = azurerm_user_assigned_identity.storage_encryption.principal_id
    foundation = {
      resource_id        = azurerm_user_assigned_identity.deployment["foundation"].id
      client_id          = azurerm_user_assigned_identity.deployment["foundation"].client_id
      principal_id       = azurerm_user_assigned_identity.deployment["foundation"].principal_id
      github_environment = "${var.environment}-foundation"
    }
    backend = {
      resource_group_name  = azurerm_resource_group.bootstrap.name
      storage_account_name = azurerm_storage_account.state[0].name
      container_name       = "foundation"
      key                  = "terraform.tfstate"
      subscription_id      = var.subscription_id
      tenant_id            = var.tenant_id
      client_id            = azurerm_user_assigned_identity.deployment["foundation"].client_id
      use_azuread_auth     = true
      use_oidc             = true
      use_cli              = false
    }
  } : null
}

data "external" "application_contract" {
  count   = local.application_enabled ? 1 : 0
  program = ["python3", "${path.module}/../../../scripts/application_contract.py", "external"]
  query = {
    context   = jsonencode(local.application_context)
    bootstrap = var.application_bootstrap_json
    artifacts = jsonencode(var.application_artifacts)
    phase     = var.application_phase
  }
}

resource "azurerm_resource_group" "application" {
  count    = local.application_enabled ? 1 : 0
  name     = local.application_namespace
  location = var.location
  tags     = merge(local.tags, { component = "application-governance" })

  lifecycle {
    prevent_destroy = true
  }
  depends_on = [data.external.application_contract]
}

resource "azurerm_key_vault" "application" {
  provider                   = azurerm.application
  count                      = local.application_enabled ? 1 : 0
  name                       = local.application_vault_name
  resource_group_name        = azurerm_resource_group.application[0].name
  location                   = azurerm_resource_group.application[0].location
  tenant_id                  = var.tenant_id
  sku_name                   = "standard"
  enable_rbac_authorization  = true
  soft_delete_retention_days = 90
  purge_protection_enabled   = true
  tags                       = merge(local.tags, { component = "application-governance" })

  network_acls {
    default_action = "Deny"
    bypass         = "AzureServices"
    ip_rules       = var.application_allowed_ip_ranges
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "azurerm_role_definition" "application_foundation" {
  count              = local.application_enabled ? 1 : 0
  name               = "Canopex ${var.environment} application foundation"
  role_definition_id = local.application_role_uuid
  scope              = azurerm_resource_group.application[0].id
  assignable_scopes  = [azurerm_resource_group.application[0].id]
  description        = "Application resource lifecycle only; governance owns namespace, vault control plane and all grants."

  permissions {
    actions          = local.application_actions
    not_actions      = []
    data_actions     = []
    not_data_actions = []
  }

  lifecycle {
    postcondition {
      condition     = self.role_definition_resource_id == "/subscriptions/${var.subscription_id}/providers/Microsoft.Authorization/roleDefinitions/${local.application_role_uuid}"
      error_message = "The provider's actual role ID must match the versioned namespace contract; stop rather than publish a guessed role ID."
    }
  }
}

resource "azurerm_role_assignment" "application_foundation" {
  count                            = local.application_enabled ? 1 : 0
  scope                            = azurerm_resource_group.application[0].id
  role_definition_id               = azurerm_role_definition.application_foundation[0].role_definition_resource_id
  principal_id                     = azurerm_user_assigned_identity.deployment["foundation"].principal_id
  skip_service_principal_aad_check = true
}

resource "azurerm_role_assignment" "application_custody" {
  count                            = local.application_custody_phases ? 1 : 0
  scope                            = azurerm_key_vault.application[0].id
  role_definition_id               = "/subscriptions/${var.subscription_id}/providers/Microsoft.Authorization/roleDefinitions/14b46e9e-c2b7-41b4-b07b-48a6ebf60603"
  principal_id                     = azurerm_user_assigned_identity.deployment["foundation"].principal_id
  skip_service_principal_aad_check = true
}

resource "azurerm_role_assignment" "application_encryption" {
  count                            = local.application_enabled && var.application_phase == "encryption" ? 1 : 0
  scope                            = data.external.application_contract[0].result.scope
  role_definition_id               = data.external.application_contract[0].result.role_definition_id
  principal_id                     = data.external.application_contract[0].result.principal_id
  skip_service_principal_aad_check = true
  depends_on                       = [azurerm_role_assignment.application_custody]
}

output "application_contract" {
  description = "Separate versioned application declaration, not effective permissions; bootstrap_contract v1 remains unchanged."
  value       = local.application_enabled ? jsondecode(data.external.application_contract[0].result.contract) : null
  depends_on = [
    azurerm_key_vault.application,
    azurerm_role_assignment.application_foundation,
    azurerm_role_assignment.application_custody,
    azurerm_role_assignment.application_encryption,
  ]
}

output "application_contract_json" {
  description = "Export with tofu output -raw; preserve these exact bytes when hashing the next-stage predecessor."
  value       = local.application_enabled ? data.external.application_contract[0].result.contract : null
  depends_on = [
    azurerm_key_vault.application,
    azurerm_role_assignment.application_foundation,
    azurerm_role_assignment.application_custody,
    azurerm_role_assignment.application_encryption,
  ]
}

output "application_contract_context_json" {
  description = "Non-secret context for separate approval/custody before foundation validates the raw artifact bundle."
  value       = local.application_enabled ? jsonencode(local.application_context) : null
}
