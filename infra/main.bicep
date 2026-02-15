// ---------------------------------------------------------------------------
// main.bicep — KML Satellite Imagery Pipeline Infrastructure
// ---------------------------------------------------------------------------
// Orchestrates all Azure resources required for the KML ingestion and
// satellite imagery acquisition workflow.
//
// Usage:
//   az deployment group create \
//     --resource-group <rg-name> \
//     --template-file infra/main.bicep \
//     --parameters infra/parameters/dev.bicepparam
//
// See: PID §8 (Technology Stack), §11 (Security), §7.5 (Compute Decision)
// ---------------------------------------------------------------------------

targetScope = 'resourceGroup'

// ---------------------------------------------------------------------------
// Parameters
// ---------------------------------------------------------------------------

@description('Azure region for all resources. Defaults to the resource group location.')
param location string = resourceGroup().location

@description('Base name for resource naming. Used as a prefix/suffix across all modules.')
@minLength(3)
@maxLength(16)
param baseName string

@description('Environment name (dev, staging, prod).')
@allowed(['dev', 'staging', 'prod'])
param environment string = 'dev'

@description('Log Analytics retention in days.')
@minValue(30)
@maxValue(730)
param logRetentionInDays int = 90

@description('Function App maximum instance count.')
param functionAppMaxInstances int = 40

@description('Function App instance memory in MB.')
@allowed([512, 2048, 4096])
param functionAppInstanceMemoryMB int = 2048

@description('Enable Key Vault purge protection. Disable only for dev/test teardown.')
param enableKeyVaultPurgeProtection bool = true

@description('Tags to apply to all resources.')
param tags object = {}

// ---------------------------------------------------------------------------
// Computed values
// ---------------------------------------------------------------------------

var defaultTags = union(tags, {
  project: 'kml-satellite'
  environment: environment
  'managed-by': 'bicep'
})

// ---------------------------------------------------------------------------
// Modules
// ---------------------------------------------------------------------------

module storage 'modules/storage.bicep' = {
  name: 'storage'
  params: {
    location: location
    baseName: baseName
    tags: defaultTags
  }
}

module monitoring 'modules/monitoring.bicep' = {
  name: 'monitoring'
  params: {
    location: location
    baseName: baseName
    retentionInDays: logRetentionInDays
    tags: defaultTags
  }
}

module keyVault 'modules/keyvault.bicep' = {
  name: 'keyvault'
  params: {
    location: location
    baseName: baseName
    tenantId: subscription().tenantId
    enablePurgeProtection: enableKeyVaultPurgeProtection
    softDeleteRetentionInDays: 90
    tags: defaultTags
  }
}

module functionApp 'modules/function-app.bicep' = {
  name: 'function-app'
  params: {
    location: location
    baseName: baseName
    storageAccountName: storage.outputs.name
    storageConnectionString: storage.outputs.connectionString
    appInsightsConnectionString: monitoring.outputs.connectionString
    keyVaultUri: keyVault.outputs.uri
    maximumInstanceCount: functionAppMaxInstances
    instanceMemoryMB: functionAppInstanceMemoryMB
    tags: defaultTags
  }
}

module eventGrid 'modules/event-grid.bicep' = {
  name: 'event-grid'
  params: {
    location: location
    baseName: baseName
    storageAccountId: storage.outputs.id
    functionAppId: functionApp.outputs.id
    tags: defaultTags
  }
}

module rbac 'modules/rbac.bicep' = {
  name: 'rbac'
  params: {
    principalId: functionApp.outputs.principalId
    storageAccountId: storage.outputs.id
    keyVaultId: keyVault.outputs.id
  }
}

// ---------------------------------------------------------------------------
// Outputs
// ---------------------------------------------------------------------------

@description('Name of the deployed storage account.')
output storageAccountName string = storage.outputs.name

@description('Name of the deployed Function App.')
output functionAppName string = functionApp.outputs.name

@description('Default hostname of the Function App.')
output functionAppHostName string = functionApp.outputs.defaultHostName

@description('Name of the deployed Key Vault.')
output keyVaultName string = keyVault.outputs.name

@description('Application Insights instrumentation key.')
output appInsightsInstrumentationKey string = monitoring.outputs.instrumentationKey
