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
// Return the resource group name after the deployment finishes.
output resourceGroupName string = resourceGroup.name
