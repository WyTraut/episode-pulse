targetScope = 'resourceGroup'

@description('Globally unique name for the Event Hubs namespace')
@minLength(6)
@maxLength(50)
param eventHubNamespaceName string

@description('Name of the Event Hub that receives normalized observations')
param eventHubName string = 'observations'

@description('Name of the existing managed identity used by the ingestion Function')
param functionIdentityName string

@description('Azure region for Event Hubs')
param location string

@description('Deployment environment')
param environment string

// Built-in Azure Event Hubs Data Sender role.
var eventHubsDataSenderRoleId = '2b629674-e913-4c01-ae53-ef4638d8f975'

// Reuse the Function identity created by function-app.bicep.
resource functionIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' existing = {
  name: functionIdentityName
}

// Basic keeps the development environment inexpensive while one downstream
// Fabric Eventstream consumes the data.
resource eventHubNamespace 'Microsoft.EventHub/namespaces@2024-01-01' = {
  name: eventHubNamespaceName
  location: location
  sku: {
    name: 'Basic'
    tier: 'Basic'
    capacity: 1
  }
  properties: {
    disableLocalAuth: true
    minimumTlsVersion: '1.2'
    publicNetworkAccess: 'Enabled'
  }
  tags: {
    application: 'EpisodePulse'
    environment: environment
    managedBy: 'Bicep'
  }
}

// Hold one day of normalized observations across two partitions.
resource observationsEventHub 'Microsoft.EventHub/namespaces/eventhubs@2024-01-01' = {
  parent: eventHubNamespace
  name: eventHubName
  properties: {
    messageRetentionInDays: 1
    partitionCount: 2
    status: 'Active'
  }
}

// Permit the Function to send events, but not read or manage Event Hubs.
resource functionSenderRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(observationsEventHub.id, functionIdentity.id, eventHubsDataSenderRoleId)
  scope: observationsEventHub
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      eventHubsDataSenderRoleId
    )
    principalId: functionIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

output fullyQualifiedNamespace string = '${eventHubNamespace.name}.servicebus.windows.net'
output eventHubName string = observationsEventHub.name
