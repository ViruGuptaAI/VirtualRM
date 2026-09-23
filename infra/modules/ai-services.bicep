// ─── AI Services — LLM Resource (South India) ───────────────────────────────
// Provisions Azure AI Services account with the LLM model deployment.
// Voice Live (in Central India) routes here via BYOM profile.

@description('Name of the AI Services account')
param name string

@description('Azure region')
param location string

@description('Resource tags')
param tags object = {}

@description('Model to deploy for Voice Live API')
param modelName string = 'gpt-4.1-mini'

@description('SKU name for the model deployment (Standard for regional deployments like southindia)')
@allowed(['GlobalStandard', 'Standard', 'DataZoneStandard'])
param modelSkuName string = 'Standard'

@description('Principal ID of the managed identity to grant Cognitive Services User')
param managedIdentityPrincipalId string

@description('Principal ID of the Voice Live resource system identity (for BYOM cross-resource access)')
param voiceLiveIdentityPrincipalId string

resource aiServices 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: name
  location: location
  tags: tags
  kind: 'AIServices'
  sku: {
    name: 'S0'
  }
  properties: {
    customSubDomainName: name
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: true
  }
}

// Deploy the Voice Live model
resource modelDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: aiServices
  name: modelName
  sku: {
    name: modelSkuName
    capacity: 50
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: modelName
      version: '2025-04-14'
    }
  }
}

// Grant Cognitive Services User role to managed identity (for Container App to call this resource)
resource cognitiveServicesUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(aiServices.id, managedIdentityPrincipalId, 'a97b65f3-24c7-4388-baec-2e87135dc908')
  scope: aiServices
  properties: {
    principalId: managedIdentityPrincipalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'a97b65f3-24c7-4388-baec-2e87135dc908') // Cognitive Services User
    principalType: 'ServicePrincipal'
  }
}

// Grant Foundry User role to Voice Live's system identity (required for BYOM cross-resource auth)
resource foundryUserRoleForVoiceLive 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(aiServices.id, voiceLiveIdentityPrincipalId, '53ca6127-db72-4b80-b1b0-d745d6d5456d')
  scope: aiServices
  properties: {
    principalId: voiceLiveIdentityPrincipalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '53ca6127-db72-4b80-b1b0-d745d6d5456d') // Foundry User
    principalType: 'ServicePrincipal'
  }
}

output endpoint string = 'https://${name}.services.ai.azure.com'
output name string = aiServices.name
output id string = aiServices.id
