// ---------------------------------------------------------------------------
// Staging environment parameters — KML Satellite Pipeline
// ---------------------------------------------------------------------------
// Staging mirrors production behavior for integration testing while remaining
// safe to tear down and recreate.
// ---------------------------------------------------------------------------

using '../main.bicep'

param location = 'uksouth'
param baseName = 'kmlsat-staging'
param environment = 'staging'
param logRetentionInDays = 90
param enableKeyVaultPurgeProtection = false
param enableEventGridSubscription = true
param tags = {
  costCenter: 'staging'
}
