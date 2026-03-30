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

output "site_url" {
  value       = var.custom_domain != "" ? "https://${var.custom_domain}" : "https://${azurerm_static_web_app.main.default_host_name}"
  description = "Primary site URL (custom domain if configured, otherwise default)."
}

output "appinsights_connection_string" {
  value       = azurerm_application_insights.main.connection_string
  description = "Application Insights connection string for browser SDK."
}

output "email_sender_address" {
  value       = var.enable_email ? "DoNotReply@${azurerm_email_communication_service_domain.azure_managed[0].mail_from_sender_domain}" : ""
  description = "Azure-managed sender address for email notifications."
}
