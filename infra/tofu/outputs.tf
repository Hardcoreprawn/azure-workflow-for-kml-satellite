output "resource_group_name" {
  value       = azurerm_resource_group.main.name
  description = "Resource group name."
}

output "storage_account_name" {
  value       = azurerm_storage_account.main.name
  description = "Storage account name."
}

output "function_app_name" {
  value       = azapi_resource.function_app.name
  description = "Function app name."
}

output "function_app_default_hostname" {
  value       = azapi_resource.function_app.output.properties.defaultHostName
  description = "Function app default hostname."
}

output "function_app_cli_app_settings" {
  value       = local.function_app_cli_app_settings
  description = "CLI-managed Function App app settings sourced from Terraform."
}

output "function_app_cli_maximum_instance_count" {
  value       = var.function_max_instances
  description = "CLI-managed Function App maximum instance count sourced from Terraform."
}

output "static_web_app_name" {
  value       = azurerm_static_web_app.main.name
  description = "Static Web App name."
}

output "static_web_app_default_hostname" {
  value       = azurerm_static_web_app.main.default_host_name
  description = "Static Web App default hostname."
}

output "event_grid_system_topic_name" {
  value       = azapi_resource.event_grid_system_topic.name
  description = "Event Grid system topic name."
}

output "custom_domain" {
  value       = var.custom_domain
  description = "Custom domain name (empty string if not configured)."
}

output "browser_allowed_origins" {
  value       = local.browser_allowed_origins
  description = "Browser origins allowed for Function App and blob upload CORS."
}

output "site_url" {
  value       = local.primary_site_url
  description = "Primary site URL (custom domain if configured, otherwise default)."
}

output "appinsights_connection_string" {
  value       = azurerm_application_insights.main.connection_string
  description = "Application Insights connection string for browser SDK."
  sensitive   = true
}

output "email_sender_address" {
  value       = var.enable_email ? "DoNotReply@${azurerm_email_communication_service_domain.azure_managed[0].mail_from_sender_domain}" : ""
  description = "Azure-managed sender address for email notifications."
}

output "cosmos_endpoint" {
  value       = var.enable_cosmos_db ? azurerm_cosmosdb_account.main[0].endpoint : ""
  description = "Cosmos DB for NoSQL endpoint URI."
}

output "cosmos_database_name" {
  value       = var.enable_cosmos_db ? azurerm_cosmosdb_sql_database.main[0].name : ""
  description = "Cosmos DB database name."
}
