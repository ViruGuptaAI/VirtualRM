// ─── Container App ──────────────────────────────────────────────────────────
// Azure Container App with managed identity, env vars, and ingress

@description('Name of the Container App')
param name string

@description('Azure region')
param location string

@description('Resource tags')
param tags object = {}

@description('Login server of the Container Registry')
param containerRegistryLoginServer string

@description('Container image override (empty = use placeholder for first deploy)')
param containerImage string = ''

@description('Resource ID of the user-assigned managed identity')
param managedIdentityId string

@description('Client ID of the user-assigned managed identity')
param managedIdentityClientId string

@description('Resource ID of the delegated Container Apps infrastructure subnet')
param infrastructureSubnetId string

@description('Endpoint for Azure AI Services (Voice Live API)')
param aiServicesEndpoint string

@description('Voice Live model deployment name')
param voiceLiveModel string = 'gpt-4.1-mini'

@description('BYOM profile for cross-resource LLM routing')
param byomProfile string = ''

@description('Foundry resource name for BYOM override (just the resource name, not full URL)')
param foundryResourceOverride string = ''

@description('Whether inbound ACS telephony routes are enabled')
param acsTelephonyEnabled bool = false

@description('Communication Services endpoint')
param acsEndpoint string = ''

@description('Communication Services Azure resource ID used for Event Grid provenance')
param acsResourceId string = ''

@description('Communication Services immutable resource ID used as callback JWT audience')
param acsCallbackAudience string = ''

@description('Azure Table endpoint for shared call state')
param acsTableEndpoint string = ''

@description('Azure Table name for shared call state')
param acsTableName string = 'acscallstate'

@description('Optional demo customer used when inbound caller ID is not present in the synthetic CRM')
param acsDemoCustomerId string = ''

var abbrs = loadJsonContent('../abbreviations.json')
var _containerImage = !empty(containerImage) ? containerImage : 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'

// ─── Log Analytics Workspace ────────────────────────────────────────────────
resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${abbrs.logAnalyticsWorkspace}${name}'
  location: location
  tags: tags
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

// ─── Container App Environment ──────────────────────────────────────────────
resource containerAppEnv 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${abbrs.containerAppEnvironment}${name}'
  location: location
  tags: tags
  properties: {
    vnetConfiguration: {
      infrastructureSubnetId: infrastructureSubnetId
      internal: false
    }
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: logAnalytics.listKeys().primarySharedKey
      }
    }
  }
}

// ─── Container App ──────────────────────────────────────────────────────────
resource containerApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: name
  location: location
  tags: union(tags, { 'azd-service-name': 'app' })
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${managedIdentityId}': {}
    }
  }
  properties: {
    managedEnvironmentId: containerAppEnv.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
        allowInsecure: false
      }
      registries: [
        {
          server: containerRegistryLoginServer
          identity: managedIdentityId
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'virtualrm'
          image: _containerImage
          resources: {
            cpu: json('1.0')
            memory: '2Gi'
          }
          env: [
            {
              name: 'AZURE_VOICE_LIVE_ENDPOINT'
              value: aiServicesEndpoint
            }
            {
              name: 'VOICE_LIVE_MODEL'
              value: voiceLiveModel
            }
            {
              name: 'AZURE_USER_ASSIGNED_IDENTITY_CLIENT_ID'
              value: managedIdentityClientId
            }
            {
              name: 'AZURE_VOICE_LIVE_API_KEY'
              value: ''
            }
            {
              name: 'BYOM_PROFILE'
              value: byomProfile
            }
            {
              name: 'FOUNDRY_RESOURCE_OVERRIDE'
              value: foundryResourceOverride
            }
            {
              name: 'ACS_TELEPHONY_ENABLED'
              value: string(acsTelephonyEnabled)
            }
            {
              name: 'ACS_ENDPOINT'
              value: acsEndpoint
            }
            {
              name: 'ACS_RESOURCE_ID'
              value: acsResourceId
            }
            {
              name: 'ACS_CALLBACK_AUDIENCE'
              value: acsCallbackAudience
            }
            {
              name: 'ACS_CALLBACK_BASE_URL'
              value: 'https://${name}.${containerAppEnv.properties.defaultDomain}'
            }
            {
              name: 'ACS_CALL_STATE_TABLE_ENDPOINT'
              value: acsTableEndpoint
            }
            {
              name: 'ACS_CALL_STATE_TABLE_NAME'
              value: acsTableName
            }
            {
              name: 'ACS_DEMO_CUSTOMER_ID'
              value: acsDemoCustomerId
            }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 5
        rules: [
          {
            name: 'http-scaling'
            http: {
              metadata: {
                concurrentRequests: '20'
              }
            }
          }
        ]
      }
    }
  }
}

output name string = containerApp.name
output fqdn string = containerApp.properties.configuration.ingress.fqdn
output id string = containerApp.id
