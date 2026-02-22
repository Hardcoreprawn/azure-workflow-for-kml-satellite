// ---------------------------------------------------------------------------
// resources.bicep — Resource-group-scoped module
// ---------------------------------------------------------------------------
// Contains all application resources. Called from main.bicep which creates
// the resource group and scopes this module into it.
//
// This file is NOT deployed directly — it's consumed as a module by
// main.bicep. To deploy the full stack, use main.bicep at subscription scope.
// ---------------------------------------------------------------------------

targetScope = 'resourceGroup'

// ---------------------------------------------------------------------------
// Parameters (passed from main.bicep)
// ---------------------------------------------------------------------------

@description('Azure region for all resources.')
param location string

@description('Base name for resource naming.')
@minLength(3)
@maxLength(16)
param baseName string

@description('Log Analytics retention in days.')
@minValue(30)
@maxValue(730)
param logRetentionInDays int

@description('Enable Key Vault purge protection.')
param enableKeyVaultPurgeProtection bool

@description('Enable Event Grid subscription (requires function code deployed).')
param enableEventGridSubscription bool = false

@description('Container image URI for the Function App.')
param containerImage string = 'mcr.microsoft.com/azure-functions/python:4-python3.12'

@description('Tags to apply to all resources.')
param tags object

// ---------------------------------------------------------------------------
// Modules
// ---------------------------------------------------------------------------

module storage 'modules/storage.bicep' = {
  name: 'storage'
  params: {
    location: location
    baseName: baseName
    tags: tags
  }
}

module monitoring 'modules/monitoring.bicep' = {
  name: 'monitoring'
  params: {
    location: location
    baseName: baseName
    retentionInDays: logRetentionInDays
    tags: tags
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
    tags: tags
  }
}

module containerEnvironment 'modules/container-environment.bicep' = {
  name: 'container-environment'
  params: {
    location: location
    baseName: baseName
    logAnalyticsWorkspaceName: monitoring.outputs.logAnalyticsWorkspaceName
    tags: tags
  }
}

module functionApp 'modules/function-app.bicep' = {
  name: 'function-app'
  params: {
    location: location
    baseName: baseName
    containerEnvironmentId: containerEnvironment.outputs.id
    storageConnectionString: storage.outputs.connectionString
    appInsightsConnectionString: monitoring.outputs.connectionString
    keyVaultUri: keyVault.outputs.uri
    containerImage: containerImage
    tags: tags
  }
}

module eventGrid 'modules/event-grid.bicep' = {
  name: 'event-grid'
  params: {
    location: location
    baseName: baseName
    storageAccountId: storage.outputs.id
    functionAppId: functionApp.outputs.id
    enableSubscription: enableEventGridSubscription
    tags: tags
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
// Outputs (surfaced to main.bicep)
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
