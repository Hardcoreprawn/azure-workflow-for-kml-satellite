// ---------------------------------------------------------------------------
// Function App — Flex Consumption plan with system-assigned Managed Identity
// Runs Python 3.12 on Linux. Custom Docker container for GDAL support.
// ---------------------------------------------------------------------------

@description('Azure region for the Function App.')
param location string

@description('Base name used for resource naming.')
param baseName string

@description('Name of the storage account (used to construct deployment blob URL).')
param storageAccountName string

@description('Connection string for the storage account used by Durable Functions.')
@secure()
param storageConnectionString string

@description('Application Insights connection string for telemetry.')
param appInsightsConnectionString string

@description('Key Vault URI for secret references.')
param keyVaultUri string

@description('Maximum instance count for scaling.')
param maximumInstanceCount int = 40

@description('Instance memory in MB (Flex Consumption).')
@allowed([512, 2048, 4096])
param instanceMemoryMB int = 2048

@description('Tags to apply to all resources.')
param tags object = {}

// ---------------------------------------------------------------------------
// App Service Plan — Flex Consumption (FC1)
// ---------------------------------------------------------------------------
resource hostingPlan 'Microsoft.Web/serverfarms@2024-04-01' = {
  name: 'plan-${baseName}'
  location: location
  tags: tags
  kind: 'functionapp'
  sku: {
    tier: 'FlexConsumption'
    name: 'FC1'
  }
  properties: {
    reserved: true // Required for Linux
  }
}

// ---------------------------------------------------------------------------
// Function App
// ---------------------------------------------------------------------------
resource functionApp 'Microsoft.Web/sites@2024-04-01' = {
  name: 'func-${baseName}'
  location: location
  tags: tags
  kind: 'functionapp,linux'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: hostingPlan.id
    httpsOnly: true
    functionAppConfig: {
      deployment: {
        storage: {
          type: 'blobContainer'
          value: 'https://${storageAccountName}.blob.${environment().suffixes.storage}/deployments'
          authentication: {
            type: 'StorageAccountConnectionString'
            storageAccountConnectionStringName: 'DEPLOYMENT_STORAGE_CONNECTION_STRING'
          }
        }
      }
      scaleAndConcurrency: {
        maximumInstanceCount: maximumInstanceCount
        instanceMemoryMB: instanceMemoryMB
      }
      runtime: {
        name: 'python'
        version: '3.12'
      }
    }
    siteConfig: {
      appSettings: [
        {
          name: 'AzureWebJobsStorage'
          value: storageConnectionString
        }
        {
          name: 'DEPLOYMENT_STORAGE_CONNECTION_STRING'
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
          name: 'KML_INPUT_CONTAINER'
          value: 'kml-input'
        }
        {
          name: 'KML_OUTPUT_CONTAINER'
          value: 'kml-output'
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
