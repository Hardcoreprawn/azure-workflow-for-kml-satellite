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
      id = "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-kmlsat-dev-bootstrap/providers/Microsoft.KeyVault/vaults/bootstrap-dev"
    }
  }
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
  environment                  = "dev"
  location                     = "westeurope"
  subscription_id              = "11111111-1111-4111-8111-111111111111"
  tenant_id                    = "22222222-2222-4222-8222-222222222222"
  project_code                 = "kmlsat"
  bootstrap_operator_object_id = "99999999-9999-4999-8999-999999999999"
}

run "reject_trust_before_state_phase" {
  command = plan
  variables {
    enable_github_oidc = true
  }
  expect_failures = [var.enable_github_oidc]
}

run "reject_unknown_phase" {
  command = plan
  variables {
    bootstrap_phase             = "unknown"
    state_key_expiration_date   = "2030-01-01T00:00:00Z"
    bootstrap_allowed_ip_ranges = ["203.0.113.10"]
  }
  expect_failures = [var.bootstrap_phase]
}

run "reject_unapproved_key_custodian" {
  command = plan
  variables {
    bootstrap_operator_object_id = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
  }
  expect_failures = [azurerm_role_assignment.key_custodian]
}

run "reject_deployment_identity_as_custodian" {
  command = plan
  variables {
    bootstrap_operator_object_id = "33333333-3333-4333-8333-333333333333"
  }
  override_data {
    target = data.azurerm_client_config.operator
    values = {
      object_id = "33333333-3333-4333-8333-333333333333"
    }
  }
  expect_failures = [azurerm_role_assignment.key_custodian]
}

run "reject_missing_key_expiry" {
  command = plan
  variables {
    bootstrap_phase             = "key"
    bootstrap_allowed_ip_ranges = ["203.0.113.10"]
  }
  expect_failures = [var.state_key_expiration_date]
}

run "expired_input_reaches_effective_key_check_not_variable_age_gate" {
  command = plan
  variables {
    bootstrap_phase             = "key"
    state_key_expiration_date   = "2000-01-01T00:00:00Z"
    bootstrap_allowed_ip_ranges = ["203.0.113.10"]
  }
  expect_failures = [azurerm_key_vault_key.state]
}

run "reject_unbounded_network" {
  command = plan
  variables {
    bootstrap_allowed_ip_ranges = ["0.0.0.0/0"]
  }
  expect_failures = [var.bootstrap_allowed_ip_ranges]
}

run "reject_private_network_range" {
  command = plan
  variables {
    bootstrap_allowed_ip_ranges = ["10.0.0.0/24"]
  }
  expect_failures = [var.bootstrap_allowed_ip_ranges]
}

run "reject_31_network_mask" {
  command = plan
  variables {
    bootstrap_allowed_ip_ranges = ["203.0.113.10/31"]
  }
  expect_failures = [var.bootstrap_allowed_ip_ranges]
}

run "reject_32_network_mask" {
  command = plan
  variables {
    bootstrap_allowed_ip_ranges = ["203.0.113.10/32"]
  }
  expect_failures = [var.bootstrap_allowed_ip_ranges]
}

run "reject_ipv6_network" {
  command = plan
  variables {
    bootstrap_allowed_ip_ranges = ["2001:db8::1"]
  }
  expect_failures = [var.bootstrap_allowed_ip_ranges]
}

run "reject_malformed_network" {
  command = plan
  variables {
    bootstrap_allowed_ip_ranges = ["999.1.1.1"]
  }
  expect_failures = [var.bootstrap_allowed_ip_ranges]
}

run "reject_key_without_network_gate" {
  command = plan
  variables {
    bootstrap_phase           = "key"
    state_key_expiration_date = "2030-01-01T00:00:00Z"
  }
  expect_failures = [var.bootstrap_allowed_ip_ranges]
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
