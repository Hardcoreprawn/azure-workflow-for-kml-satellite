// ---------------------------------------------------------------------------
// Key Vault — Centralised secret management
// Uses RBAC authorisation (not access policies) for Managed Identity access.
// ---------------------------------------------------------------------------

@description('Azure region for the Key Vault.')
param location string

@description('Base name used for resource naming.')
param baseName string

@description('Tenant ID for the Key Vault.')
param tenantId string

@description('Enable soft-delete protection.')
param enablePurgeProtection bool = true

@description('Soft-delete retention in days.')
@minValue(7)
@maxValue(90)
param softDeleteRetentionInDays int = 90

@description('Tags to apply to all resources.')
param tags object = {}

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: 'kv-${baseName}'
  location: location
  tags: tags
  properties: {
    tenantId: tenantId
    sku: {
      family: 'A'
      name: 'standard'
    }
    enableRbacAuthorization: true
    enableSoftDelete: true
    enablePurgeProtection: enablePurgeProtection
    softDeleteRetentionInDays: softDeleteRetentionInDays
    networkAcls: {
      defaultAction: 'Allow' // Tighten in production
      bypass: 'AzureServices'
    }
  }
}

@description('Resource ID of the Key Vault.')
output id string = keyVault.id

@description('Name of the Key Vault.')
output name string = keyVault.name

@description('URI of the Key Vault.')
output uri string = keyVault.properties.vaultUri
