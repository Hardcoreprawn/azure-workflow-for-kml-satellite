// ---------------------------------------------------------------------------
// RBAC Assignments — Managed Identity access to Storage & Key Vault
// Uses Azure built-in role definitions.
// ---------------------------------------------------------------------------

@description('Principal ID of the Function App managed identity.')
param principalId string

@description('Resource ID of the storage account.')
param storageAccountId string

@description('Resource ID of the Key Vault.')
param keyVaultId string

// ---------------------------------------------------------------------------
// Built-in Role Definition IDs
// https://learn.microsoft.com/azure/role-based-access-control/built-in-roles
// ---------------------------------------------------------------------------

@description('Storage Blob Data Contributor role definition ID.')
var storageBlobDataContributorRoleId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'

@description('Key Vault Secrets User role definition ID.')
var keyVaultSecretsUserRoleId = '4633458b-17de-408a-b874-0445c86b69e6'

// ---------------------------------------------------------------------------
// Storage Blob Data Contributor — Function App → Storage Account
// Allows read/write/delete of blob data via Managed Identity.
// ---------------------------------------------------------------------------
resource storageBlobContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccountId, principalId, storageBlobDataContributorRoleId)
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributorRoleId)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}

// ---------------------------------------------------------------------------
// Key Vault Secrets User — Function App → Key Vault
// Allows reading secrets (imagery API keys, provider credentials).
// ---------------------------------------------------------------------------
resource kvSecretsUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVaultId, principalId, keyVaultSecretsUserRoleId)
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsUserRoleId)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}

// ---------------------------------------------------------------------------
// Existing resource references (scoped role assignments)
// ---------------------------------------------------------------------------
resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: last(split(storageAccountId, '/'))!
}

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: last(split(keyVaultId, '/'))!
}
