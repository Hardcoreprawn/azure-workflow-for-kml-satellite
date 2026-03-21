#!/usr/bin/env bash
# Bootstrap the Azure resources needed for OpenTofu remote state.
# Run this ONCE before the first `tofu init`.
#
# Prerequisites:
#   - az cli logged in (`az login`)
#   - Subscription selected (`az account set -s <id>`)
#
set -euo pipefail

RESOURCE_GROUP="treesight-tfstate"
STORAGE_ACCOUNT="treesighttfstate"
CONTAINER="tfstate"
LOCATION="westeurope"

echo "Creating resource group: $RESOURCE_GROUP"
az group create \
  --name "$RESOURCE_GROUP" \
  --location "$LOCATION" \
  --output none

echo "Creating storage account: $STORAGE_ACCOUNT"
az storage account create \
  --name "$STORAGE_ACCOUNT" \
  --resource-group "$RESOURCE_GROUP" \
  --location "$LOCATION" \
  --sku Standard_LRS \
  --min-tls-version TLS1_2 \
  --allow-blob-public-access false \
  --output none

echo "Creating blob container: $CONTAINER"
az storage container create \
  --name "$CONTAINER" \
  --account-name "$STORAGE_ACCOUNT" \
  --auth-mode login \
  --output none

echo ""
echo "Done. Remote state backend is ready."
echo "Run: cd infra && tofu init"
