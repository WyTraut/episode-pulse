targetScope = 'resourceGroup'

param storageAccountName string
param location string
param environment string

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageAccountName
  location: location
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
  }
  tags: {
    application: 'EpisodePulse'
    environment: environment
    managedBy: 'Bicep'
  }
}
// Enable blob storage within the storage account.
resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storageAccount
  name: 'default'
}

// Create a private container for untouched Trakt API responses.
resource rawContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'raw'
  properties: {
    publicAccess: 'None'
  }
}

// Store compact, dashboard-ready data separately from immutable raw responses.
resource servingContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'serving'
  properties: {
    publicAccess: 'None'
  }
}

// Store deployed Azure Function code packages.
resource functionDeploymentContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'function-deployments'
  properties: {
    publicAccess: 'None'
  }
}

output storageAccountId string = storageAccount.id
output blobEndpoint string = storageAccount.properties.primaryEndpoints.blob
output servingContainerName string = servingContainer.name
output functionDeploymentContainerName string = functionDeploymentContainer.name
