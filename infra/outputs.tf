# ─────────────────────────────────────────────────────────────
# Outputs
# ─────────────────────────────────────────────────────────────

output "resource_group_name" {
  value = azurerm_resource_group.main.name
}

output "acr_login_server" {
  value = azurerm_container_registry.acr.login_server
}

output "acr_name" {
  value = azurerm_container_registry.acr.name
}

output "storage_account_name" {
  value = azurerm_storage_account.main.name
}

output "functions_url" {
  value = "https://${azurerm_container_app.functions.ingress[0].fqdn}"
}

output "static_web_app_url" {
  value = "https://${azurerm_static_web_app.website.default_host_name}"
}

output "static_web_app_api_key" {
  value     = azurerm_static_web_app.website.api_key
  sensitive = true
}

output "application_insights_connection_string" {
  value     = azurerm_application_insights.main.connection_string
  sensitive = true
}

output "key_vault_name" {
  value = azurerm_key_vault.main.name
}
