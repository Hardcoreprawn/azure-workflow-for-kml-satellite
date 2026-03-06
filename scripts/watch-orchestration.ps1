#!/usr/bin/env pwsh
<#
.SYNOPSIS
  Watch Azure Durable Functions orchestration with real-time progress.

.PARAMETER InstanceId
  Durable Functions orchestration instance ID.

.PARAMETER Timeout
  Maximum wait time in minutes (default: 20).

.EXAMPLE
  .\watch-orchestration.ps1 -InstanceId bec2a3f3004f4131a5577a136a46f2bf -Timeout 20
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$InstanceId,
    [int]$Timeout = 20
)

$maxWaitSec = $Timeout * 60
$startTime = Get-Date
$lastStatus = ""
$pollIntervalSec = 30

Write-Host "⏳ Watching orchestration: $InstanceId`n"

function Get-StatusEmoji {
    param([string]$Status)
    switch ($Status) {
        "Completed" { "✅" }
        "Failed" { "❌" }
        "Terminated" { "⏹️ " }
        "Running" { "⏳" }
        "Pending" { "⏳" }
        default { "❓" }
    }
}

function Get-OrchestratorStatus {
    param([string]$InstanceId)

    # Use Azure CLI with explicit error handling
    try {
        $jsonOut = & az durable-functions instance show --id $InstanceId -g rg-kmlsat-dev 2>$null | ConvertFrom-Json
        return $jsonOut
    } catch {
        return $null
    }
}

# Main polling loop
while ($true) {
    $elapsed = [math]::Round(((Get-Date) - $startTime).TotalSeconds)
    $elapsedMin = [math]::Floor($elapsed / 60)
    $elapsedSec = $elapsed % 60

    # Hard timeout
    if ($elapsed -ge $maxWaitSec) {
        Write-Host "`n⏱️  Timeout reached after ${Timeout}m"
        Write-Host "   Orchestration may still be running — check status manually"
        exit 1
    }

    # Fetch and display status
    $status = Get-OrchestratorStatus -InstanceId $InstanceId

    if ($status) {
        $currentStatus = $status.runtimeStatus

        if ($currentStatus -ne $lastStatus) {
            $emoji = Get-StatusEmoji $currentStatus
            Write-Host "$emoji [$($elapsedMin)m:$($elapsedSec | ForEach-Object {'{0:D2}' -f $_})s] $currentStatus"
            $lastStatus = $currentStatus
        }

        # Terminal states
        if (@("Completed", "Failed", "Terminated") -contains $currentStatus) {
            Write-Host ""
            if ($currentStatus -eq "Completed") {
                Write-Host "✅ Orchestration completed successfully"
                if ($status.output) {
                    Write-Host "   Result: $(($status.output | ConvertTo-Json -Compress) -replace '"','')"
                }
            } elseif ($currentStatus -eq "Failed") {
                Write-Host "❌ Orchestration failed"
                if ($status.output) {
                    Write-Host "   Error: $($status.output)"
                }
            }
            exit 0
        }
    } else {
        Write-Host "⏳ [$($elapsedMin)m:$($elapsedSec | ForEach-Object {'{0:D2}' -f $_})s] Checking... (may be cold-starting)"
    }

    Start-Sleep -Seconds $pollIntervalSec
}
