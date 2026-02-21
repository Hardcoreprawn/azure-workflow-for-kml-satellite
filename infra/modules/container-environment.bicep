// ---------------------------------------------------------------------------
// Container Apps Environment — hosts the Function App container
// Uses the existing Log Analytics workspace for structured application logging.
// ---------------------------------------------------------------------------

@description('Azure region for the Container Apps environment.')
param location string

@description('Base name used for resource naming.')
param baseName string

@description('Name of the Log Analytics workspace for application logs.')
param logAnalyticsWorkspaceName string

@description('Tags to apply to all resources.')
param tags object = {}

// Reference the existing Log Analytics workspace deployed by monitoring module
resource logAnalyticsWorkspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: logAnalyticsWorkspaceName
}

resource containerEnvironment 'Microsoft.App/managedEnvironments@2023-05-01' = {
  name: 'cae-${baseName}'
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalyticsWorkspace.properties.customerId
        sharedKey: logAnalyticsWorkspace.listKeys().primarySharedKey
      }
    }
  }
}

@description('Resource ID of the Container Apps environment.')
output id string = containerEnvironment.id

@description('Name of the Container Apps environment.')
output name string = containerEnvironment.name
