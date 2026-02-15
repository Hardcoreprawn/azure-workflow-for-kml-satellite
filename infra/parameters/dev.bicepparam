// ---------------------------------------------------------------------------
// Dev environment parameters — KML Satellite Pipeline
// ---------------------------------------------------------------------------
// Optimised for development: lower resources, purge protection off for
// easy teardown, shorter log retention.
// ---------------------------------------------------------------------------

using '../main.bicep'

param baseName = 'kmlsat-dev'
param environment = 'dev'
param logRetentionInDays = 30
param functionAppMaxInstances = 10
param functionAppInstanceMemoryMB = 2048
param enableKeyVaultPurgeProtection = false
param tags = {
  costCenter: 'dev'
}
