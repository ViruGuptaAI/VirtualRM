// ─── AI Services (Microsoft Foundry) ─────────────────────────────────────────
// Provisions Azure AI Services account with Voice Live API model deployment

@description('Name of the AI Services account')
param name string

@description('Azure region')
param location string

@description('Resource tags')
param tags object = {}

@description('Model to deploy for Voice Live API')
param modelName string = 'gpt-4.1-mini'

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
  properties: {
    customSubDomainName: name
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: false
  }
}

// Deploy the Voice Live model
resource modelDeployment 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: aiServices
  name: modelName
  sku: {
    name: 'GlobalStandard'
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
