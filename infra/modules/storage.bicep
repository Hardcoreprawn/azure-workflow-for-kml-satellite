// ---------------------------------------------------------------------------
// Storage Account — GPv2, Hot tier
// Two containers: kml-input (Event Grid source) and kml-output (processed)
// ---------------------------------------------------------------------------

@description('Azure region for the storage account.')
param location string

@description('Base name used to generate a unique storage account name.')
@minLength(3)
@maxLength(16)
param baseName string

@description('Tags to apply to all resources.')
param tags object = {}

// Storage account names must be globally unique, lowercase, 3-24 chars
var storageAccountName = toLower('st${replace(baseName, '-', '')}${uniqueString(resourceGroup().id)}')

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: take(storageAccountName, 24)
  location: location
  tags: tags
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
  properties: {
    accessTier: 'Hot'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: true // Required for Durable Functions storage provider
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    networkAcls: {
      defaultAction: 'Allow' // Tighten in production via parameters
      bypass: 'AzureServices'
    }
  }
}

resource blobServices 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storageAccount
  name: 'default'
}

resource kmlInputContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobServices
  name: 'kml-input'
  properties: {
    publicAccess: 'None'
  }
}

resource kmlOutputContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobServices
  name: 'kml-output'
  properties: {
    publicAccess: 'None'
  }
}

// Lifecycle management — archive old imagery, delete old logs
resource lifecyclePolicy 'Microsoft.Storage/storageAccounts/managementPolicies@2023-05-01' = {
  parent: storageAccount
  name: 'default'
  properties: {
    policy: {
      rules: [
        {
          name: 'archive-raw-imagery-180d'
          enabled: true
          type: 'Lifecycle'
          definition: {
            actions: {
              baseBlob: {
                tierToCool: {
                  daysAfterModificationGreaterThan: 180
                }
              }
            }
            filters: {
              blobTypes: ['blockBlob']
              prefixMatch: ['kml-output/imagery/raw/']
            }
          }
        }
        {
          name: 'archive-raw-imagery-365d'
          enabled: true
          type: 'Lifecycle'
          definition: {
            actions: {
              baseBlob: {
                tierToArchive: {
                  daysAfterModificationGreaterThan: 365
                }
              }
            }
            filters: {
              blobTypes: ['blockBlob']
              prefixMatch: ['kml-output/imagery/raw/']
            }
          }
        }
      ]
    }
  }
}

@description('Resource ID of the storage account.')
output id string = storageAccount.id

@description('Name of the storage account.')
output name string = storageAccount.name

@description('Primary connection string (for Durable Functions hub). Required by Durable Functions storage provider.')
#disable-next-line outputs-should-not-contain-secrets
output connectionString string = 'DefaultEndpointsProtocol=https;AccountName=${storageAccount.name};AccountKey=${storageAccount.listKeys().keys[0].value};EndpointSuffix=${environment().suffixes.storage}'
