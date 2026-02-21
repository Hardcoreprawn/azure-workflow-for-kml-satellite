// ---------------------------------------------------------------------------
// Production environment parameters — KML Satellite Pipeline
// ---------------------------------------------------------------------------
// Production-grade settings: purge protection enabled, higher instance
// count, longer log retention.
// ---------------------------------------------------------------------------

using '../main.bicep'

param location = 'uksouth'
param baseName = 'kmlsat-prod'
param environment = 'prod'
param logRetentionInDays = 365
param enableKeyVaultPurgeProtection = true
param tags = {
  costCenter: 'production'
}
