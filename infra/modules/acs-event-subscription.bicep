@description('Existing Communication Services resource name')
param communicationServiceName string

@description('Public HTTPS endpoint for Event Grid incoming-call delivery')
@secure()
param callbackUrl string

resource communicationService 'Microsoft.Communication/communicationServices@2023-04-01' existing = {
  name: communicationServiceName
}

resource incomingCallSubscription 'Microsoft.EventGrid/eventSubscriptions@2023-12-15-preview' = {
  name: 'virtualrm-incoming-calls'
  scope: communicationService
  properties: {
    destination: {
      endpointType: 'WebHook'
      properties: {
        endpointUrl: callbackUrl
      }
    }
    eventDeliverySchema: 'EventGridSchema'
    filter: {
      includedEventTypes: [
        'Microsoft.Communication.IncomingCall'
      ]
    }
    retryPolicy: {
      eventTimeToLiveInMinutes: 1440
      maxDeliveryAttempts: 10
    }
  }
}

output eventSubscriptionId string = incomingCallSubscription.id
