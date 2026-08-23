// This file deploys resources at the Azure subscription level.
targetScope = 'subscription'

// Inputs that can change between deployments.
@description('Globally unique name for the storage account')
param storageAccountName string

@description('Azure region where the resources will be deployed')
param location string = 'centralus'

@description('Deployment environment, such as dev, test, or prod')
param environment string = 'dev'

@description('Short code for the selected Azure region')
param regionCode string = 'cus'

@description('Globally unique name for the Key Vault')
param keyVaultName string

@description('Globally unique name for the Azure Function App')
param functionAppName string

@description('Globally unique name for the Event Hubs namespace')
param eventHubNamespaceName string

@description('Globally unique name for the public EpisodePulse web application')
param webAppName string

@description('App Service plan size. Use F1 while developing and B1 when Always On is needed.')
@allowed([
  'F1'
  'B1'
])
param appServiceSkuName string = 'F1'

// Build a consistent resource group name from the environment and region.
var resourceGroupName = 'rg-epulse-${environment}-${regionCode}'


// Create the resource group that will contain the EpisodePulse resources.
resource resourceGroup 'Microsoft.Resources/resourceGroups@2025-04-01' = {
  name: resourceGroupName
  location: location
  tags: {
    application: 'EpisodePulse'
    environment: environment
    managedBy: 'Bicep'
  }
}
module storageModule './storage.bicep' = {
  name: 'storageDeployment'
  scope: resourceGroup
  params: {
    storageAccountName: storageAccountName
    location: location
    environment: environment
  }
}
// Deploy Key Vault inside the EpisodePulse resource group.
module keyVaultModule './key-vault.bicep' = {
  name: 'keyVaultDeployment'
  scope: resourceGroup
  params: {
    keyVaultName: keyVaultName
    location: location
    environment: environment
  }
}

// Deploy the EpisodePulse ingestion Function App.
module functionAppModule './function-app.bicep' = {
  name: 'functionAppDeployment'
  scope: resourceGroup
  params: {
    keyVaultName: keyVaultName
    storageAccountName: storageAccountName
    functionAppName: functionAppName
    location: location
    environment: environment
    storageBlobEndpoint: storageModule.outputs.blobEndpoint
    functionDeploymentContainerName: storageModule.outputs.functionDeploymentContainerName
    servingContainerName: storageModule.outputs.servingContainerName
    eventHubNamespaceName: eventHubNamespaceName
    eventHubName: 'observations'
  }
  dependsOn: [
    keyVaultModule
  ]
}

// Create the stream that carries normalized observations to Microsoft Fabric.
module eventHubModule './event-hub.bicep' = {
  name: 'eventHubDeployment'
  scope: resourceGroup
  params: {
    eventHubNamespaceName: eventHubNamespaceName
    eventHubName: 'observations'
    functionIdentityName: 'id-${functionAppName}'
    location: location
    environment: environment
  }
  dependsOn: [
    functionAppModule
  ]
}

// Deploy the public API that reads the private dashboard serving projection.
module appServiceModule './app-service.bicep' = {
  name: 'appServiceDeployment'
  scope: resourceGroup
  params: {
    webAppName: webAppName
    location: location
    environment: environment
    storageAccountName: storageAccountName
    servingContainerName: storageModule.outputs.servingContainerName
    applicationInsightsName: 'appi-${functionAppName}'
    appServiceSkuName: appServiceSkuName
  }
  dependsOn: [
    functionAppModule
  ]
}


// Return the resource group name after the deployment finishes.
output resourceGroupName string = resourceGroup.name
output webAppUrl string = appServiceModule.outputs.webAppUrl
