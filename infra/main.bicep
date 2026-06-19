targetScope = 'subscription'

// ─── Parameters ─────────────────────────────────────────────────────────────
@minLength(1)
@maxLength(64)
@description('Name of the environment (used as resource prefix)')
param environmentName string

@minLength(1)
@description('Primary Azure region for all resources')
param location string

@description('Name of the resource group (defaults to rg-{environmentName})')
param resourceGroupName string = ''

@description('Name for the Container App (defaults to ca-{environmentName})')
param containerAppName string = ''

@description('Name for the Container Registry (defaults to cr{environmentName})')
param containerRegistryName string = ''

@description('Name for the AI Services account (defaults to ai-{environmentName})')
param aiServicesName string = ''

@description('Voice Live model deployment name')
param voiceLiveModel string = 'gpt-4.1-mini'

// ─── Variables ──────────────────────────────────────────────────────────────
var abbrs = loadJsonContent('./abbreviations.json')
var resourceToken = toLower(uniqueString(subscription().id, environmentName, location))
var _rgName = !empty(resourceGroupName) ? resourceGroupName : '${abbrs.resourceGroup}${environmentName}'
var _containerAppName = !empty(containerAppName) ? containerAppName : '${abbrs.containerApp}${environmentName}'
var _containerRegistryName = !empty(containerRegistryName) ? containerRegistryName : '${abbrs.containerRegistry}${resourceToken}'
var _aiServicesName = !empty(aiServicesName) ? aiServicesName : '${abbrs.aiServices}${environmentName}'
var tags = {
  'azd-env-name': environmentName
  project: 'virtualrm'
}

// ─── Resource Group ─────────────────────────────────────────────────────────
resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: _rgName
  location: location
  tags: tags
}

// ─── Managed Identity ───────────────────────────────────────────────────────
module identity './modules/managed-identity.bicep' = {
  name: 'managed-identity'
  scope: rg
  params: {
    name: '${abbrs.managedIdentity}${environmentName}'
    location: location
    tags: tags
  }
}

// ─── Container Registry ─────────────────────────────────────────────────────
module acr './modules/container-registry.bicep' = {
  name: 'container-registry'
  scope: rg
  params: {
    name: _containerRegistryName
    location: location
    tags: tags
    managedIdentityPrincipalId: identity.outputs.principalId
  }
}

// ─── AI Services (Voice Live API) ───────────────────────────────────────────
module aiServices './modules/ai-services.bicep' = {
  name: 'ai-services'
  scope: rg
  params: {
    name: _aiServicesName
    location: location
    tags: tags
    modelName: voiceLiveModel
    managedIdentityPrincipalId: identity.outputs.principalId
  }
}

// ─── Container App ──────────────────────────────────────────────────────────
module containerApp './modules/container-app.bicep' = {
  name: 'container-app'
  scope: rg
  params: {
    name: _containerAppName
    location: location
    tags: tags
    containerRegistryLoginServer: acr.outputs.loginServer
    managedIdentityId: identity.outputs.id
    managedIdentityClientId: identity.outputs.clientId
    aiServicesEndpoint: aiServices.outputs.endpoint
    voiceLiveModel: voiceLiveModel
  }
}

// ─── Outputs (consumed by azd) ──────────────────────────────────────────────
output AZURE_RESOURCE_GROUP string = rg.name
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = acr.outputs.loginServer
output AZURE_CONTAINER_REGISTRY_NAME string = acr.outputs.name
output AZURE_CONTAINER_APP_NAME string = containerApp.outputs.name
output AZURE_CONTAINER_APP_FQDN string = containerApp.outputs.fqdn
output AZURE_VOICE_LIVE_ENDPOINT string = aiServices.outputs.endpoint
output AZURE_USER_ASSIGNED_IDENTITY_CLIENT_ID string = identity.outputs.clientId
output VOICE_LIVE_MODEL string = voiceLiveModel
