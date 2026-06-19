// ─── Managed Identity ───────────────────────────────────────────────────────
// User-assigned managed identity for Container App → ACR pull + AI Services access

@description('Name of the managed identity')
param name string

@description('Azure region')
param location string

@description('Resource tags')
param tags object = {}

resource managedIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: name
  location: location
  tags: tags
}

output id string = managedIdentity.id
output clientId string = managedIdentity.properties.clientId
output principalId string = managedIdentity.properties.principalId
output name string = managedIdentity.name
