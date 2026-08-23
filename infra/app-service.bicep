targetScope = 'resourceGroup'

@description('Globally unique name for the public EpisodePulse web application')
param webAppName string

@description('Azure region for App Service')
param location string

@description('Deployment environment')
param environment string

@description('Existing EpisodePulse storage account name')
param storageAccountName string

@description('Private container that holds dashboard-ready data')
param servingContainerName string

@description('Existing Application Insights resource used by EpisodePulse')
param applicationInsightsName string

@description('App Service plan size. F1 is free; B1 supports Always On and more traffic.')
@allowed([
  'F1'
  'B1'
])
param appServiceSkuName string = 'F1'

var appServicePlanName = 'plan-${webAppName}'
var appServiceSkuTier = appServiceSkuName == 'F1' ? 'Free' : 'Basic'
var storageBlobDataReaderRoleId = '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1'

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' existing = {
  parent: storageAccount
  name: 'default'
}

resource servingContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' existing = {
  parent: blobService
  name: servingContainerName
}

resource applicationInsights 'Microsoft.Insights/components@2020-02-02' existing = {
  name: applicationInsightsName
}

// Start with the free App Service tier while the portfolio application is small.
resource appServicePlan 'Microsoft.Web/serverfarms@2024-04-01' = {
  name: appServicePlanName
  location: location
  kind: 'linux'
  sku: {
    name: appServiceSkuName
    tier: appServiceSkuTier
    capacity: 1
  }
  properties: {
    reserved: true
  }
  tags: {
    application: 'EpisodePulse'
    environment: environment
    managedBy: 'Bicep'
  }
}

// Host the public API without placing a storage key in application settings.
resource webApp 'Microsoft.Web/sites@2024-04-01' = {
  name: webAppName
  location: location
  kind: 'app,linux'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: appServicePlan.id
    httpsOnly: true
    clientAffinityEnabled: false
    publicNetworkAccess: 'Enabled'
    siteConfig: {
      linuxFxVersion: 'PYTHON|3.12'
      appCommandLine: 'gunicorn --bind=0.0.0.0:8000 --workers=2 --worker-class=uvicorn.workers.UvicornWorker app:app'
      alwaysOn: appServiceSkuName != 'F1'
      ftpsState: 'Disabled'
      http20Enabled: true
      minTlsVersion: '1.2'
    }
  }
  tags: {
    application: 'EpisodePulse'
    environment: environment
    managedBy: 'Bicep'
  }
}

// Give the web app read-only access to only the serving container.
resource servingBlobReaderRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(servingContainer.id, webApp.id, storageBlobDataReaderRoleId)
  scope: servingContainer
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      storageBlobDataReaderRoleId
    )
    principalId: webApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource webAppSettings 'Microsoft.Web/sites/config@2024-04-01' = {
  parent: webApp
  name: 'appsettings'
  properties: {
    SCM_DO_BUILD_DURING_DEPLOYMENT: 'true'
    ENABLE_ORYX_BUILD: 'true'
    DATA_STORAGE_ACCOUNT_NAME: storageAccount.name
    SERVING_CONTAINER_NAME: servingContainer.name
    APPLICATIONINSIGHTS_CONNECTION_STRING: applicationInsights.properties.ConnectionString
  }
}

output webAppName string = webApp.name
output webAppUrl string = 'https://${webApp.properties.defaultHostName}'
