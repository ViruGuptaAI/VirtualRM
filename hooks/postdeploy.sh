#!/bin/bash
# Post-deploy hook: print the app URL
echo ""
echo "=============================================="
echo "  VirtualRM deployed successfully!"
echo "=============================================="
echo ""
echo "  App URL: https://${AZURE_CONTAINER_APP_FQDN}"
echo ""
echo "  Demo login: rajesh / contoso123"
echo ""
echo "=============================================="
