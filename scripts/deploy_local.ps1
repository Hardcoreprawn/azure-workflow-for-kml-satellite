#!/usr/bin/env pwsh

# ---------------------------------------------------------------------------
# deploy_local.ps1 — Manual "Margaret Hamilton" Deployment Script
# ---------------------------------------------------------------------------
# DEPRECATED: This script uses legacy Bicep templates. Infrastructure is now
# managed by OpenTofu (infra/tofu/). To deploy locally:
#
# Option 1: Use GitHub Actions workflows (recommended)
#   - Merge to main to trigger tofu-apply.yml and deploy.yml
#   - This is the source of truth for deployment logic
#
# Option 2: Manual local OpenTofu deployment
#   cd infra/tofu
#   tofu init (use -backend-config flags for state backend)
#   tofu plan -var-file="environments/dev.tfvars"
#   tofu apply
#
# Then build and push the container:
#   docker build -t ghcr.io/yourname/image:latest .
#   docker push ghcr.io/yourname/image:latest
#   az functionapp config container set \
#     --name func-kmlsat-dev \
#     --resource-group rg-kmlsat-dev \
#     --docker-custom-image-name ghcr.io/yourname/image:latest \
#     --docker-registry-server-url https://ghcr.io \
#     --docker-registry-server-username $GITHUB_ACTOR \
#     --docker-registry-server-password $GITHUB_TOKEN
#
# Archived Bicep-based logic is kept below for reference, but should not be used.
# ---------------------------------------------------------------------------

param(
    [string]$Location = "uksouth",
    [string]$Environment = "dev",
    [string]$ContainerImage = "mcr.microsoft.com/azure-functions/python:4-python3.12"
)

$ErrorActionPreference = "Stop"

function Log($Msg) { Write-Host "$(Get-Date -Format 'HH:mm:ss') | $Msg" -ForegroundColor Cyan }
function Warn($Msg) { Write-Host "$(Get-Date -Format 'HH:mm:ss') | WARNING: $Msg" -ForegroundColor Yellow }
function Err($Msg) { Write-Host "$(Get-Date -Format 'HH:mm:ss') | ERROR: $Msg" -ForegroundColor Red }

# ---------------------------------------------------------------------------
# 1. Validation
# ---------------------------------------------------------------------------
Log "Validating prerequisites..."
if (-not (Get-Command "az" -ErrorAction SilentlyContinue)) { Err "Azure CLI (az) not found."; exit 1 }
if (-not (Get-Command "jq" -ErrorAction SilentlyContinue)) { Err "jq not found."; exit 1 }
if (-not (Get-Command "curl" -ErrorAction SilentlyContinue)) { Err "curl not found."; exit 1 }

if ($ContainerImage -eq "mcr.microsoft.com/azure-functions/python:4-python3.12") {
    Warn "Using default Microsoft image. Function 'kml_blob_trigger' will NOT be present."
    Warn "Expect the health check (Step 4) to fail unless you provide a custom image."
    Warn "Usage: ./deploy_local.ps1 -ContainerImage <myregistry.azurecr.io/myimage:tag>"
    Start-Sleep -Seconds 3
}

$SubId = az account show --query id -o tsv
if (-not $SubId) { Err "Not logged in to Azure."; exit 1 }
Log "Target Subscription: $SubId"
Log "Target Environment: $Environment ($Location)"
Log "Container Image: $ContainerImage"

# ---------------------------------------------------------------------------
# 2. Pass 1: Infrastructure + App (No Subscription)
# ---------------------------------------------------------------------------
Log "::group::Pass 1 - Deploying Infrastructure & App (Subscription Disabled)"
$DeploymentName1 = "deploy-infra-$(Get-Date -Format 'yyyyMMdd-HHmm')"

try {
    az deployment sub create `
        --name $DeploymentName1 `
        --location $Location `
        --template-file infra/main.bicep `
        --parameters infra/parameters/${Environment}.bicepparam `
        --parameters enableEventGridSubscription=false `
        --parameters containerImage=$ContainerImage | Out-Null

    Log "✔ Pass 1 Deployment Complete."
}
catch {
    Err "Pass 1 Deployment Failed."
    Write-Host $_
    exit 1
}
Log "::endgroup::"

# ---------------------------------------------------------------------------
# 3. Retrieve Outputs
# ---------------------------------------------------------------------------
Log "Retrieving deployment outputs..."
$Outputs = az deployment sub show --name $DeploymentName1 --query properties.outputs -o json | ConvertFrom-Json
$FunctionAppName = $Outputs.functionAppName.value
$ResourceGroup = "rg-kmlsat-${Environment}" # Derived convention
$HostName = $Outputs.functionAppHostName.value

Log "  Function App: $FunctionAppName"
Log "  Resource Group: $ResourceGroup"
Log "  Hostname: $HostName"

# ---------------------------------------------------------------------------
# 4. Wait for Host & Function Indexing (The "Margaret Hamilton" Logic)
# ---------------------------------------------------------------------------
Log "::group::Waiting for kml_blob_trigger to be discoverable"

# Get Master Key
Log "Retrieving Host Master Key..."
$HostKey = ""
for ($i = 1; $i -le 10; $i++) {
    $ResourceId = "/subscriptions/${SubId}/resourceGroups/${ResourceGroup}/providers/Microsoft.Web/sites/${FunctionAppName}"
    $HostKey = az rest --method post --uri "https://management.azure.com${ResourceId}/host/default/listKeys?api-version=2024-04-01" --query "masterKey" -o tsv 2>$null
    if ($HostKey) { break }
    Log "  Attempt $i/10: Key not ready. Sleeping 5s..."
    Start-Sleep -Seconds 5
}

if (-not $HostKey) { Err "Failed to get Host Master Key."; exit 1 }
Log "✔ Host Master Key retrieved."

# Poll for kml_blob_trigger
$StartTime = Get-Date
$MaxDuration = New-TimeSpan -Minutes 5

if ($ContainerImage -like "*mcr.microsoft.com*") {
    Warn "Using default image - cannot wait for 'kml_blob_trigger'."
    Warn "Verify the host is running, but skipping function discovery check."
    Start-Sleep -Seconds 10
    $Found = $true
} else {
    $Found = $false
    while ((Get-Date) -lt $StartTime.Add($MaxDuration)) {
        $Elapsed = [math]::Round(((Get-Date) - $StartTime).TotalSeconds)

        # Check Host Status
        $HostStatusJson = curl -sS --max-time 10 -H "x-functions-key: $HostKey" "https://${HostName}/admin/host/status" | Out-String
        $State = $HostStatusJson | jq -r '.state // "Unknown"' 2>$null

        if ($State -ne "Running") {
            Log "  [${Elapsed}s] Host State: '$State'. Waiting..."
            Start-Sleep -Seconds 10
            continue
        }

        # Check Function Index
        $FuncStatusJson = curl -sS --max-time 10 -H "x-functions-key: $HostKey" "https://${HostName}/admin/functions/kml_blob_trigger/status" | Out-String
        $FuncName = $FuncStatusJson | jq -r '.name // empty' 2>$null

        if ($FuncName -eq "kml_blob_trigger") {
            Log "✔ Function 'kml_blob_trigger' is indexed and ready."
            $Found = $true
            break
        } else {
            Log "  [${Elapsed}s] Function not found in registry yet. Retrying..."
            Start-Sleep -Seconds 5
        }
    }
}

Log "::endgroup::"

if (-not $Found) {
    Warn "Timeout reached. Proceeding to Pass 2 anyway (Event Grid checks will likely fail/retry)."
}

# ---------------------------------------------------------------------------
# 5. Pass 2: Enable Subscription
# ---------------------------------------------------------------------------
Log "::group::Pass 2 - Enabling Event Grid Subscription"
$MaxAttempts = 5
$Success = $false

for ($i = 1; $i -le $MaxAttempts; $i++) {
    Log "Attempt $i/$MaxAttempts..."
    $DeploymentName2 = "deploy-eg-$(Get-Date -Format 'yyyyMMdd-HHmm')-$i"

    try {
        # Using --no-wait is risky here as we want to capture the error immediately
        az deployment sub create `
            --name $DeploymentName2 `
            --location $Location `
            --template-file infra/main.bicep `
            --parameters infra/parameters/${Environment}.bicepparam `
            --parameters enableEventGridSubscription=true `
            --parameters containerImage='mcr.microsoft.com/azure-functions/python:4-python3.12' | Out-Null

        Log "✔ Pass 2 Deployment Complete."
        $Success = $true
        break
    }
    catch {
        Warn "Pass 2 attempt failed."
        Write-Host $_
        Start-Sleep -Seconds 10
    }
}

if (-not $Success) { Err "Failed to enable Event Grid Subscription."; exit 1 }
Log "::endgroup::"

Log "✅ Manual deployment successful. Environment is ready."
