#!/bin/bash
# Post-deploy hook: create the Event Grid subscription after the app route is live.
set -euo pipefail

if [ "${ACS_TELEPHONY_ENABLED:-true}" != "false" ]; then
	az deployment group create \
		--resource-group "${AZURE_RESOURCE_GROUP}" \
		--name acs-incoming-call-event-subscription \
		--template-file infra/modules/acs-event-subscription.bicep \
		--parameters communicationServiceName="${AZURE_COMMUNICATION_SERVICE_NAME}" \
								 callbackUrl="https://${AZURE_CONTAINER_APP_FQDN}/api/acs/incoming-call" \
		--only-show-errors >/dev/null
fi

echo ""
echo "=============================================="
echo "  VirtualRM deployed successfully!"
echo "=============================================="
echo ""
echo "  App URL: https://${AZURE_CONTAINER_APP_FQDN}"
echo "  ACS resource: ${AZURE_COMMUNICATION_SERVICE_NAME}"
echo ""
echo "  Demo login: rajesh / contoso123"
echo ""
echo "=============================================="
