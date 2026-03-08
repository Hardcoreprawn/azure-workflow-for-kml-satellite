param(
    [Parameter(Mandatory = $true)]
    [string]$SubscriptionId,

    [Parameter(Mandatory = $true)]
    [string]$StateResourceGroup,

    [Parameter(Mandatory = $true)]
    [string]$StateStorageAccount,

    [Parameter(Mandatory = $true)]
    [string]$StateContainer,

    [string]$StateKey = "kml-satellite-dev.tfstate",
    [string]$ResourceGroupName = "rg-kmlsat-dev",
    [switch]$SkipDelete
)

$ErrorActionPreference = "Stop"

Write-Host "== OpenTofu Dev Rebuild ==" -ForegroundColor Cyan
Write-Host "Subscription: $SubscriptionId"
Write-Host "Resource Group: $ResourceGroupName"
Write-Host "State: $StateResourceGroup/$StateStorageAccount/$StateContainer/$StateKey"

az account set --subscription $SubscriptionId | Out-Null

if (-not $SkipDelete) {
    Write-Host "\n[1/5] Deleting existing dev resource group..." -ForegroundColor Yellow
    if (az group exists --name $ResourceGroupName | ConvertFrom-Json) {
        az group delete --name $ResourceGroupName --yes --no-wait | Out-Null
        az group wait --name $ResourceGroupName --deleted
        Write-Host "Deleted $ResourceGroupName" -ForegroundColor Green
    }
    else {
        Write-Host "Resource group does not exist, continuing." -ForegroundColor DarkYellow
    }
}
else {
    Write-Host "\n[1/5] SkipDelete enabled. Reusing existing resource group if present." -ForegroundColor DarkYellow
}

Push-Location "$PSScriptRoot\..\infra\tofu"

Write-Host "\n[2/5] Initializing OpenTofu backend..." -ForegroundColor Yellow
tofu init \
    -backend-config="resource_group_name=$StateResourceGroup" \
    -backend-config="storage_account_name=$StateStorageAccount" \
    -backend-config="container_name=$StateContainer" \
    -backend-config="key=$StateKey"

Write-Host "\n[3/5] Validating configuration..." -ForegroundColor Yellow
tofu validate

Write-Host "\n[4/5] Planning dev environment..." -ForegroundColor Yellow
tofu plan \
    -var="subscription_id=$SubscriptionId" \
    -var-file="environments/dev.tfvars" \
    -out="dev.tfplan"

Write-Host "\n[5/5] Applying dev environment..." -ForegroundColor Yellow
tofu apply -auto-approve "dev.tfplan"

Pop-Location

Write-Host "\nDev rebuild complete." -ForegroundColor Green
Write-Host "Next: deploy app image and static site workflows." -ForegroundColor Cyan
