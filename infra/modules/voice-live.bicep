// ─── Voice Live Resource (Central India) ─────────────────────────────────────
// Provisions Azure AI Services account for Voice Live API (STT + TTS + managed LLM).
// In "default" mode: Voice Live handles LLM inference internally (no model deployment needed).
// In "byom" mode: Voice Live routes LLM to an external Foundry resource via BYOM profile.

@description('Name of the AI Services account for Voice Live')
param name string

@description('Azure region (Voice Live available in centralindia)')
param location string

@description('Resource tags')
param tags object = {}

@description('Principal ID of the managed identity to grant Cognitive Services User')
param managedIdentityPrincipalId string

resource aiServices 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: name
  location: location
  tags: tags
  kind: 'AIServices'
  sku: {
    name: 'S0'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    customSubDomainName: name
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: true
  }
}

// Grant Cognitive Services User role to managed identity
resource cognitiveServicesUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(aiServices.id, managedIdentityPrincipalId, 'a97b65f3-24c7-4388-baec-2e87135dc908')
  scope: aiServices
  properties: {
    principalId: managedIdentityPrincipalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'a97b65f3-24c7-4388-baec-2e87135dc908') // Cognitive Services User
    principalType: 'ServicePrincipal'
  }
}

output endpoint string = 'https://${name}.services.ai.azure.com'
output name string = aiServices.name
output id string = aiServices.id
output identityPrincipalId string = aiServices.identity.principalId
