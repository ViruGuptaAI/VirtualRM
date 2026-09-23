# Post-deploy hook: create the Event Grid subscription after the app route is live.
$ErrorActionPreference = 'Stop'

if ($env:ACS_TELEPHONY_ENABLED -ne 'false') {
	az deployment group create `
		--resource-group $env:AZURE_RESOURCE_GROUP `
		--name acs-incoming-call-event-subscription `
		--template-file infra/modules/acs-event-subscription.bicep `
		--parameters communicationServiceName=$env:AZURE_COMMUNICATION_SERVICE_NAME `
					 callbackUrl="https://$env:AZURE_CONTAINER_APP_FQDN/api/acs/incoming-call" `
		--only-show-errors | Out-Null
	if ($LASTEXITCODE -ne 0) { throw 'Event Grid subscription deployment failed.' }
}

Write-Host ""
Write-Host "=============================================="
Write-Host "  VirtualRM deployed successfully!"
Write-Host "=============================================="
Write-Host ""
Write-Host "  App URL: https://$env:AZURE_CONTAINER_APP_FQDN"
Write-Host "  ACS resource: $env:AZURE_COMMUNICATION_SERVICE_NAME"
Write-Host ""
Write-Host "  Demo login: rajesh / contoso123"
Write-Host ""
Write-Host "=============================================="
