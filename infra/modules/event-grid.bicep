// ---------------------------------------------------------------------------
// Event Grid — System Topic on Storage Account + Subscription for .kml files
// Triggers the Function App when a blob is created in kml-input container.
// ---------------------------------------------------------------------------

@description('Azure region for Event Grid resources.')
param location string

@description('Base name used for resource naming.')
param baseName string

@description('Resource ID of the source storage account.')
param storageAccountId string

@description('Resource ID of the target Function App.')
param functionAppId string

@description('Enable the event subscription (requires function code to be deployed first).')
param enableSubscription bool = false

@description('Tags to apply to all resources.')
param tags object = {}

// ---------------------------------------------------------------------------
// System Topic — watches the storage account for blob events
// ---------------------------------------------------------------------------
resource systemTopic 'Microsoft.EventGrid/systemTopics@2024-06-01-preview' = {
  name: 'evgt-${baseName}'
  location: location
  tags: tags
  properties: {
    source: storageAccountId
    topicType: 'Microsoft.Storage.StorageAccounts'
  }
}

// ---------------------------------------------------------------------------
// Event Subscription — filters for .kml files in kml-input container
// Delivers to the Function App's Event Grid trigger endpoint.
// ---------------------------------------------------------------------------
resource eventSubscription 'Microsoft.EventGrid/systemTopics/eventSubscriptions@2024-06-01-preview' = if (enableSubscription) {
  parent: systemTopic
  name: 'evgs-kml-upload'
  properties: {
    destination: {
      endpointType: 'AzureFunction'
      properties: {
        resourceId: '${functionAppId}/functions/kml_blob_trigger'
        maxEventsPerBatch: 1
        preferredBatchSizeInKilobytes: 64
      }
    }
    filter: {
      includedEventTypes: [
        'Microsoft.Storage.BlobCreated'
      ]
      subjectBeginsWith: '/blobServices/default/containers/kml-input/'
      subjectEndsWith: '.kml'
      isSubjectCaseSensitive: false
    }
    eventDeliverySchema: 'EventGridSchema'
    retryPolicy: {
      maxDeliveryAttempts: 30
      eventTimeToLiveInMinutes: 1440
    }
  }
}

@description('Resource ID of the Event Grid system topic.')
output systemTopicId string = systemTopic.id

@description('Name of the Event Grid system topic.')
output systemTopicName string = systemTopic.name
