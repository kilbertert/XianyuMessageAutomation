[CmdletBinding()]
param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$TaskName = "XianyuAndroidMessageGateway",
    [switch]$PurgeSecret
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($null -ne $task) {
    if ($task.State -eq "Running") {
        Stop-ScheduledTask -TaskName $TaskName
    }
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

if ($PurgeSecret) {
    $resolvedRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
    $secretPath = Join-Path $resolvedRoot "var\service\gateway-secret.dpapi"
    if (Test-Path -LiteralPath $secretPath -PathType Leaf) {
        [IO.File]::Delete($secretPath)
    }
}

@{
    installed = $false
    task_name = $TaskName
    secret_purged = [bool]$PurgeSecret
} | ConvertTo-Json -Compress
