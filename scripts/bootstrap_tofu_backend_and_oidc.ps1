param(
    [Parameter(Mandatory = $true)]
    [string]$SubscriptionId,

    [Parameter(Mandatory = $true)]
    [string]$TenantId,

    [Parameter(Mandatory = $true)]
    [string]$GitHubOwner,

    [Parameter(Mandatory = $true)]
    [string]$GitHubRepo,

    [string]$Location = "uksouth",
    [string]$StateResourceGroup = "rg-kmlsat-tofu-state",
    [string]$StateStorageAccount = "stkmlsattofustate",
    [string]$StateContainer = "tfstate",
    [string]$AppRegistrationName = "gha-kmlsat-tofu",
    [switch]$SkipIdentity
)

$ErrorActionPreference = "Stop"

Write-Host "== Bootstrap OpenTofu Backend + OIDC ==" -ForegroundColor Cyan
Write-Host "Subscription: $SubscriptionId"
Write-Host "Tenant: $TenantId"
Write-Host "Repository: $GitHubOwner/$GitHubRepo"

az account set --subscription $SubscriptionId | Out-Null

Write-Host "\n[1/5] Creating state resource group..." -ForegroundColor Yellow
az group create --name $StateResourceGroup --location $Location --tags managed-by=manual-bootstrap project=kml-satellite purpose=tofu-state | Out-Null

Write-Host "\n[2/5] Creating state storage account..." -ForegroundColor Yellow
$exists = az storage account check-name --name $StateStorageAccount --query nameAvailable -o tsv
if ($exists -eq "true") {
    az storage account create --name $StateStorageAccount --resource-group $StateResourceGroup --location $Location --sku Standard_LRS --kind StorageV2 --min-tls-version TLS1_2 --allow-blob-public-access false --allow-shared-key-access true --tags managed-by=manual-bootstrap project=kml-satellite purpose=tofu-state | Out-Null
}
else {
    Write-Host "Storage account name already in use. Assuming it already exists and continuing." -ForegroundColor DarkYellow
}

Write-Host "\n[3/5] Creating state container..." -ForegroundColor Yellow
$stateKey = az storage account keys list --resource-group $StateResourceGroup --account-name $StateStorageAccount --query "[0].value" -o tsv
az storage container create --name $StateContainer --account-name $StateStorageAccount --account-key $stateKey --auth-mode key | Out-Null

if (-not $SkipIdentity) {
    Write-Host "\n[4/5] Creating/locating Entra app registration + service principal..." -ForegroundColor Yellow
    $appId = az ad app list --display-name $AppRegistrationName --query "[0].appId" -o tsv
    if (-not $appId) {
        $appId = az ad app create --display-name $AppRegistrationName --query appId -o tsv
    }

    $spId = az ad sp list --filter "appId eq '$appId'" --query "[0].id" -o tsv
    if (-not $spId) {
        az ad sp create --id $appId | Out-Null
        Start-Sleep -Seconds 8
        $spId = az ad sp list --filter "appId eq '$appId'" --query "[0].id" -o tsv
    }

    # Contributor for initial migration convenience (can be tightened later)
    try {
        az role assignment create --assignee-object-id $spId --assignee-principal-type ServicePrincipal --role Contributor --scope "/subscriptions/$SubscriptionId" | Out-Null
    }
    catch {
        Write-Host "Contributor assignment already exists or cannot be created now. Continuing." -ForegroundColor DarkYellow
    }

    # Storage Blob Data Contributor for state operations
    try {
        az role assignment create --assignee-object-id $spId --assignee-principal-type ServicePrincipal --role "Storage Blob Data Contributor" --scope "/subscriptions/$SubscriptionId/resourceGroups/$StateResourceGroup/providers/Microsoft.Storage/storageAccounts/$StateStorageAccount" | Out-Null
    }
    catch {
        Write-Host "Storage role assignment already exists or cannot be created now. Continuing." -ForegroundColor DarkYellow
    }

    Write-Host "\n[5/5] Creating federated credentials for GitHub environments..." -ForegroundColor Yellow
    $subjects = @(
        "repo:${GitHubOwner}/${GitHubRepo}:environment:dev",
        "repo:${GitHubOwner}/${GitHubRepo}:environment:prd"
    )

    foreach ($subject in $subjects) {
        $name = ($subject -replace "[^a-zA-Z0-9-]", "-").ToLowerInvariant()
        $tmp = [System.IO.Path]::GetTempFileName()
        @"
{
  "name": "$name",
  "issuer": "https://token.actions.githubusercontent.com",
  "subject": "$subject",
  "audiences": [
    "api://AzureADTokenExchange"
  ]
}
"@ | Set-Content -Path $tmp -Encoding UTF8

        try {
            az ad app federated-credential create --id $appId --parameters "@$tmp" | Out-Null
            Write-Host "Created federated credential for $subject"
        }
        catch {
            Write-Host "Federated credential likely exists for $subject, continuing." -ForegroundColor DarkYellow
        }
        finally {
            Remove-Item $tmp -ErrorAction SilentlyContinue
        }
    }

    Write-Host "\nBootstrap complete. Configure these GitHub environment secrets for dev/prd:" -ForegroundColor Green
    Write-Host "AZURE_CLIENT_ID=$appId"
    Write-Host "AZURE_TENANT_ID=$TenantId"
    Write-Host "AZURE_SUBSCRIPTION_ID=$SubscriptionId"
    Write-Host "TF_STATE_RESOURCE_GROUP=$StateResourceGroup"
    Write-Host "TF_STATE_STORAGE_ACCOUNT=$StateStorageAccount"
    Write-Host "TF_STATE_CONTAINER=$StateContainer"
    Write-Host "TF_STATE_KEY=kml-satellite-<env>.tfstate"
}
else {
    Write-Host "\nIdentity bootstrap skipped." -ForegroundColor DarkYellow
    Write-Host "State backend created."
}
