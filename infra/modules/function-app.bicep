// ---------------------------------------------------------------------------
// Function App — Azure Functions on Container Apps
// Runs a custom Docker container with GDAL/rasterio for KML/raster ops.
// System-assigned Managed Identity for storage and Key Vault access.
// ---------------------------------------------------------------------------

@description('Azure region for the Function App.')
param location string

@description('Base name used for resource naming.')
param baseName string

@description('Resource ID of the Container Apps managed environment.')
param containerEnvironmentId string

@description('Connection string for the storage account used by Durable Functions.')
@secure()
param storageConnectionString string

@description('Application Insights connection string for telemetry.')
param appInsightsConnectionString string

@description('Key Vault URI for secret references.')
param keyVaultUri string

@description('Container image URI. Updated by the deploy workflow on each release.')
param containerImage string = 'mcr.microsoft.com/azure-functions/python:4-python3.12'

@description('Tags to apply to all resources.')
param tags object = {}

// ---------------------------------------------------------------------------
// Function App — hosted on Container Apps environment
// ---------------------------------------------------------------------------
resource functionApp 'Microsoft.Web/sites@2024-04-01' = {
  name: 'func-${baseName}'
  location: location
  tags: tags
  kind: 'functionapp,linux,container,azurecontainerapps'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    managedEnvironmentId: containerEnvironmentId
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'DOCKER|${containerImage}'
      appSettings: [
        {
          name: 'AzureWebJobsStorage'
          value: storageConnectionString
        }
        {
          name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
          value: appInsightsConnectionString
        }
        {
          name: 'KEY_VAULT_URI'
          value: keyVaultUri
        }
        {
          name: 'DEFAULT_INPUT_CONTAINER'
          value: 'kml-input' // Fallback for local dev; multi-tenant resolves dynamically
        }
        {
          name: 'DEFAULT_OUTPUT_CONTAINER'
          value: 'kml-output' // Fallback for local dev; multi-tenant resolves dynamically
        }
        {
          name: 'IMAGERY_PROVIDER'
          value: 'planetary_computer' // Default to free provider for dev
        }
      ]
    }
  }
}

@description('Resource ID of the Function App.')
output id string = functionApp.id

@description('Name of the Function App.')
output name string = functionApp.name

@description('Principal ID of the system-assigned managed identity.')
output principalId string = functionApp.identity.principalId

@description('Default hostname of the Function App.')
output defaultHostName string = functionApp.properties.defaultHostName
