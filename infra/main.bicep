// ---------------------------------------------------------------------------
// main.bicep — KML Satellite Imagery Pipeline Infrastructure
// ---------------------------------------------------------------------------
// Subscription-scoped deployment: creates the Resource Group and all
// resources within it. The RG is the application boundary — everything
// the pipeline needs lives inside it, and tearing it down removes all
// resources cleanly.
//
// Usage:
//   az deployment sub create \
//     --location uksouth \
//     --template-file infra/main.bicep \
//     --parameters infra/parameters/dev.bicepparam
//
// See: PID §8 (Technology Stack), §11 (Security), §7.5 (Compute Decision)
// ---------------------------------------------------------------------------

targetScope = 'subscription'

// ---------------------------------------------------------------------------
// Parameters
// ---------------------------------------------------------------------------

@description('Azure region for the resource group and all resources.')
param location string

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

@description('Enable Key Vault purge protection. Disable only for dev/test teardown.')
param enableKeyVaultPurgeProtection bool = true

@description('Enable Event Grid subscription. Requires function code to be deployed first.')
param enableEventGridSubscription bool = false

@description('Container image URI for the Function App. Overridden by the deploy workflow.')
param containerImage string = 'mcr.microsoft.com/azure-functions/python:4-python3.12'

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

var resourceGroupName = 'rg-${baseName}'

// ---------------------------------------------------------------------------
// Resource Group — the application boundary
// ---------------------------------------------------------------------------

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: resourceGroupName
  location: location
  tags: defaultTags
}

// ---------------------------------------------------------------------------
// All application resources — scoped to the resource group
// ---------------------------------------------------------------------------

module resources 'resources.bicep' = {
  scope: rg
  params: {
    location: location
    baseName: baseName
    logRetentionInDays: logRetentionInDays
    enableKeyVaultPurgeProtection: enableKeyVaultPurgeProtection
    enableEventGridSubscription: enableEventGridSubscription
    containerImage: containerImage
    tags: defaultTags
  }
}

// ---------------------------------------------------------------------------
// Outputs
// ---------------------------------------------------------------------------

@description('Name of the resource group.')
output resourceGroupName string = rg.name

@description('Name of the deployed storage account.')
output storageAccountName string = resources.outputs.storageAccountName

@description('Name of the deployed Function App.')
output functionAppName string = resources.outputs.functionAppName

@description('Default hostname of the Function App.')
output functionAppHostName string = resources.outputs.functionAppHostName

@description('Name of the deployed Key Vault.')
output keyVaultName string = resources.outputs.keyVaultName

@description('Application Insights instrumentation key.')
output appInsightsInstrumentationKey string = resources.outputs.appInsightsInstrumentationKey
