targetScope = 'resourceGroup'

@description('Globally unique name for the Function App')
param functionAppName string

@description('Azure region for the Function App')
param location string

@description('Deployment environment')
param environment string

@description('Blob Storage endpoint used for Function deployments')
param storageBlobEndpoint string

@description('Container that stores deployed Function code')
param functionDeploymentContainerName string

@description('Existing EpisodePulse storage account name')
param storageAccountName string

@description('Container that stores dashboard-ready serving data')
param servingContainerName string

@description('Existing EpisodePulse Key Vault name')
param keyVaultName string

@description('Event Hubs namespace used for normalized observations')
param eventHubNamespaceName string

@description('Event Hub used for normalized observations')
param eventHubName string

var hostingPlanName = 'plan-${functionAppName}'

var storageBlobDataOwnerRoleId = 'b7e6dc6d-f1e8-4753-8033-0f276bb0955b'

var keyVaultSecretsUserRoleId = '4633458b-17de-408a-b874-0445c86b69e6'

var storageQueueDataContributorRoleId = '974c5e8b-45b9-4653-ba55-5f855dd0fb88'

var storageTableDataContributorRoleId = '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3'

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
}

resource keyVaultSecretsRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, functionIdentity.id, keyVaultSecretsUserRoleId)
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      keyVaultSecretsUserRoleId
    )
    principalId: functionIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}

// Create a serverless Flex Consumption hosting plan.
resource hostingPlan 'Microsoft.Web/serverfarms@2024-04-01' = {
  name: hostingPlanName
  location: location
  kind: 'functionapp'
  sku: {
    tier: 'FlexConsumption'
    name: 'FC1'
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
// Give the Function App an Azure identity without storing passwords.
resource functionIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-${functionAppName}'
  location: location
  tags: {
    application: 'EpisodePulse'
    environment: environment
    managedBy: 'Bicep'
  }
}

// Allow the Function identity to manage blobs.
resource storageBlobRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, functionIdentity.id, storageBlobDataOwnerRoleId)
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      storageBlobDataOwnerRoleId
    )
    principalId: functionIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource storageQueueRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, functionIdentity.id, storageQueueDataContributorRoleId)
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      storageQueueDataContributorRoleId
    )
    principalId: functionIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource storageTableRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, functionIdentity.id, storageTableDataContributorRoleId)
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      storageTableDataContributorRoleId
    )
    principalId: functionIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// Store Function logs and diagnostics.
resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'log-${functionAppName}'
  location: location
  properties: {
    retentionInDays: 30
    sku: {
      name: 'PerGB2018'
    }
  }
}

// Monitor executions, failures, and performance.
resource applicationInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-${functionAppName}'
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logAnalytics.id
  }
}

// Create the Python Function App.
resource functionApp 'Microsoft.Web/sites@2024-04-01' = {
  name: functionAppName
  location: location
  kind: 'functionapp,linux'
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${functionIdentity.id}': {}
    }
  }
  properties: {
    serverFarmId: hostingPlan.id
    httpsOnly: true
    siteConfig: {
      minTlsVersion: '1.2'
    }
    functionAppConfig: {
      deployment: {
        storage: {
          type: 'blobContainer'
          value: '${storageBlobEndpoint}${functionDeploymentContainerName}'
          authentication: {
            type: 'UserAssignedIdentity'
            userAssignedIdentityResourceId: functionIdentity.id
          }
        }
      }
      scaleAndConcurrency: {
        maximumInstanceCount: 40
        instanceMemoryMB: 2048
      }
      runtime: {
        name: 'python'
        version: '3.12'
      }
    }
  }
  tags: {
    application: 'EpisodePulse'
    environment: environment
    managedBy: 'Bicep'
  }
  dependsOn: [
    storageBlobRole
    storageQueueRole
    storageTableRole
    keyVaultSecretsRole
  ]
}
// Configure the Function without storing passwords or access keys.
resource functionAppSettings 'Microsoft.Web/sites/config@2024-04-01' = {
  parent: functionApp
  name: 'appsettings'
  properties: {
    AzureWebJobsStorage__accountName: storageAccount.name
    AzureWebJobsStorage__credential: 'managedidentity'
    AzureWebJobsStorage__clientId: functionIdentity.properties.clientId
    AZURE_CLIENT_ID: functionIdentity.properties.clientId

    DATA_STORAGE_ACCOUNT_NAME: storageAccount.name
    RAW_CONTAINER_NAME: 'raw'
    SERVING_CONTAINER_NAME: servingContainerName

    KEY_VAULT_URI: keyVault.properties.vaultUri
    TRAKT_CLIENT_ID_SECRET_NAME: 'trakt-client-id'

    EVENT_HUB_FULLY_QUALIFIED_NAMESPACE: '${eventHubNamespaceName}.servicebus.windows.net'
    EVENT_HUB_NAME: eventHubName

    APPLICATIONINSIGHTS_CONNECTION_STRING: applicationInsights.properties.ConnectionString
  }
}
