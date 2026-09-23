targetScope = 'subscription'

// ─── Parameters ─────────────────────────────────────────────────────────────
@minLength(1)
@maxLength(64)
@description('Name of the environment (used as resource prefix)')
param environmentName string

@minLength(1)
@description('Primary Azure region for all resources')
param location string

@description('Deployment mode: "default" = single Foundry (model on same resource), "byom" = two Foundry resources (Voice Live + separate LLM)')
@allowed(['default', 'byom'])
param deploymentMode string = 'default'

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

@description('Region for Voice Live resource (STT + TTS)')
param voiceLiveLocation string = 'centralindia'

@description('Region for LLM resource (only used in BYOM mode)')
param llmLocation string = 'southindia'

@description('Model deployment SKU for the LLM resource')
@allowed(['GlobalStandard', 'Standard', 'DataZoneStandard'])
param modelSkuName string = 'Standard'

@description('Container image for the app (set by azd after build, uses placeholder on first deploy)')
param containerImage string = ''

@description('Enable inbound ACS telephony')
param acsTelephonyEnabled bool = true

@description('Communication Services data location')
param acsDataLocation string = 'UnitedStates'

@description('Optional synthetic CRM customer used for unmatched callers in demo environments')
param acsDemoCustomerId string = ''

// ─── Variables ──────────────────────────────────────────────────────────────
var abbrs = loadJsonContent('./abbreviations.json')
var resourceToken = toLower(uniqueString(subscription().id, environmentName, location))
var _rgName = !empty(resourceGroupName) ? resourceGroupName : '${abbrs.resourceGroup}${environmentName}'
var _containerAppName = toLower(!empty(containerAppName) ? containerAppName : '${abbrs.containerApp}${environmentName}')
var _containerRegistryName = toLower(!empty(containerRegistryName) ? containerRegistryName : '${abbrs.containerRegistry}${resourceToken}')
var _aiServicesName = !empty(aiServicesName) ? aiServicesName : '${abbrs.aiServices}${environmentName}'
var _communicationServiceName = take('acs-${environmentName}-${resourceToken}', 63)
var _callStateStorageName = take('st${replace(environmentName, '-', '')}${resourceToken}', 24)
var isByom = deploymentMode == 'byom'
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

// ─── Private Network ────────────────────────────────────────────────────────
module privateNetwork './modules/private-network.bicep' = {
  name: 'private-network'
  scope: rg
  params: {
    environmentName: environmentName
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

// ─── Voice Live Resource (Central India — STT + TTS + managed LLM) ──────────
// In "default" mode: Voice Live handles LLM inference internally — no model deployment.
// In "byom" mode: Voice Live routes LLM to the separate LLM resource via BYOM profile.
module voiceLive './modules/voice-live.bicep' = {
  name: 'voice-live'
  scope: rg
  params: {
    name: '${_aiServicesName}-voicelive'
    location: voiceLiveLocation
    tags: tags
    managedIdentityPrincipalId: identity.outputs.principalId
  }
}

// ─── LLM Resource (South India — model deployment, BYOM mode only) ──────────
// Voice Live's system identity needs 'Foundry User' on this resource for BYOM auth.
module llmServices './modules/ai-services.bicep' = if (isByom) {
  name: 'llm-services'
  scope: rg
  params: {
    name: '${_aiServicesName}-llm'
    location: llmLocation
    tags: tags
    modelName: voiceLiveModel
    modelSkuName: modelSkuName
    managedIdentityPrincipalId: identity.outputs.principalId
    voiceLiveIdentityPrincipalId: voiceLive.outputs.identityPrincipalId
  }
}

module acsTelephony './modules/acs-telephony.bicep' = if (acsTelephonyEnabled) {
  name: 'acs-telephony'
  scope: rg
  params: {
    communicationServiceName: _communicationServiceName
    storageAccountName: _callStateStorageName
    dataLocation: acsDataLocation
    managedIdentityPrincipalId: identity.outputs.principalId
    virtualNetworkId: privateNetwork.outputs.virtualNetworkId
    privateEndpointSubnetId: privateNetwork.outputs.privateEndpointsSubnetId
    tags: tags
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
    containerImage: containerImage
    managedIdentityId: identity.outputs.id
    managedIdentityClientId: identity.outputs.clientId
    infrastructureSubnetId: privateNetwork.outputs.containerAppsSubnetId
    aiServicesEndpoint: voiceLive.outputs.endpoint
    voiceLiveModel: voiceLiveModel
    byomProfile: isByom ? 'byom-azure-openai-chat-completion' : ''
    foundryResourceOverride: isByom ? '${_aiServicesName}-llm' : ''
    acsTelephonyEnabled: acsTelephonyEnabled
    acsEndpoint: acsTelephonyEnabled && acsTelephony != null ? acsTelephony!.outputs.communicationServiceEndpoint : ''
    acsResourceId: acsTelephonyEnabled && acsTelephony != null ? acsTelephony!.outputs.communicationServiceId : ''
    acsCallbackAudience: acsTelephonyEnabled && acsTelephony != null ? acsTelephony!.outputs.callbackAudience : ''
    acsTableEndpoint: acsTelephonyEnabled && acsTelephony != null ? acsTelephony!.outputs.tableEndpoint : ''
    acsTableName: acsTelephonyEnabled && acsTelephony != null ? acsTelephony!.outputs.tableName : ''
    acsDemoCustomerId: acsDemoCustomerId
  }
}

// ─── Outputs (consumed by azd) ──────────────────────────────────────────────
output AZURE_RESOURCE_GROUP string = rg.name
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = acr.outputs.loginServer
output AZURE_CONTAINER_REGISTRY_NAME string = acr.outputs.name
output AZURE_CONTAINER_APP_NAME string = containerApp.outputs.name
output AZURE_CONTAINER_APP_FQDN string = containerApp.outputs.fqdn
output AZURE_VOICE_LIVE_ENDPOINT string = voiceLive.outputs.endpoint
output AZURE_LLM_ENDPOINT string = isByom && llmServices != null ? llmServices!.outputs.endpoint : voiceLive.outputs.endpoint
output AZURE_USER_ASSIGNED_IDENTITY_CLIENT_ID string = identity.outputs.clientId
output VOICE_LIVE_MODEL string = voiceLiveModel
output DEPLOYMENT_MODE string = deploymentMode
output AZURE_COMMUNICATION_SERVICE_NAME string = acsTelephonyEnabled && acsTelephony != null ? acsTelephony!.outputs.communicationServiceName : ''
output ACS_ENDPOINT string = acsTelephonyEnabled && acsTelephony != null ? acsTelephony!.outputs.communicationServiceEndpoint : ''
output ACS_RESOURCE_ID string = acsTelephonyEnabled && acsTelephony != null ? acsTelephony!.outputs.communicationServiceId : ''
output ACS_CALLBACK_AUDIENCE string = acsTelephonyEnabled && acsTelephony != null ? acsTelephony!.outputs.callbackAudience : ''
output ACS_CALLBACK_BASE_URL string = 'https://${containerApp.outputs.fqdn}'
