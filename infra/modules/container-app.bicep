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

@description('Resource ID of the user-assigned managed identity')
param managedIdentityId string

@description('Client ID of the user-assigned managed identity')
param managedIdentityClientId string

@description('Endpoint for Azure AI Services (Voice Live API)')
param aiServicesEndpoint string

@description('Voice Live model deployment name')
param voiceLiveModel string = 'gpt-4.1-mini'

@description('BYOM profile for cross-resource LLM routing')
param byomProfile string = ''

@description('Foundry resource name for BYOM override (just the resource name, not full URL)')
param foundryResourceOverride string = ''

var abbrs = loadJsonContent('../abbreviations.json')

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
          image: '${containerRegistryLoginServer}/virtualrm:latest'
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
