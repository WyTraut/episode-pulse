targetScope = 'subscription'
param location string = 'centralus'
param environment string = 'dev'
param regionCode string = 'cus'
var resourceGroupName = 'rg-epulse-${environment}-${regionCode}'
resource resourceGroup 'Microsoft.Resources/resourceGroups@2025-04-01' = {
  name: resourceGroupName
  location: location
  tags: {
    application: 'EpisodePulse'
    environment: environment
    managedBy: 'Bicep'
  }
}
output resourceGroupName string = resourceGroup.name
