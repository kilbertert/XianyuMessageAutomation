[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [Security.SecureString]$SharedSecret,

    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$TaskName = "XianyuAndroidMessageGateway"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$resolvedRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$serviceScript = Join-Path $resolvedRoot "scripts\gateway_service.ps1"
$gatewayCli = Join-Path $resolvedRoot ".venv\Scripts\xianyu-msg.exe"
$configPath = Join-Path $resolvedRoot "config.json"
$serviceDirectory = Join-Path $resolvedRoot "var\service"
$secretPath = Join-Path $serviceDirectory "gateway-secret.dpapi"

foreach ($requiredPath in @($serviceScript, $gatewayCli, $configPath)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "Required gateway file is missing: $requiredPath"
    }
}

[IO.Directory]::CreateDirectory($serviceDirectory) | Out-Null
$identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$acl = New-Object Security.AccessControl.DirectorySecurity
$acl.SetAccessRuleProtection($true, $false)
$acl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule(
    $identity,
    [Security.AccessControl.FileSystemRights]::FullControl,
    [Security.AccessControl.InheritanceFlags]::ContainerInherit -bor [Security.AccessControl.InheritanceFlags]::ObjectInherit,
    [Security.AccessControl.PropagationFlags]::None,
    [Security.AccessControl.AccessControlType]::Allow
)))
$acl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule(
    "NT AUTHORITY\SYSTEM",
    [Security.AccessControl.FileSystemRights]::FullControl,
    [Security.AccessControl.InheritanceFlags]::ContainerInherit -bor [Security.AccessControl.InheritanceFlags]::ObjectInherit,
    [Security.AccessControl.PropagationFlags]::None,
    [Security.AccessControl.AccessControlType]::Allow
)))
Set-Acl -LiteralPath $serviceDirectory -AclObject $acl

$SharedSecret | ConvertFrom-SecureString | Set-Content -LiteralPath $secretPath -Encoding ASCII

$powerShell = (Get-Command powershell.exe).Source
$taskArguments = "-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$serviceScript`" -ProjectRoot `"$resolvedRoot`""
$action = New-ScheduledTaskAction -Execute $powerShell -Argument $taskArguments -WorkingDirectory $resolvedRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $identity
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable
$task = New-ScheduledTask -Action $action -Trigger $trigger -Principal $principal -Settings $settings

$existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($null -ne $existingTask -and $existingTask.State -eq "Running") {
    Stop-ScheduledTask -TaskName $TaskName
}
Register-ScheduledTask -TaskName $TaskName -InputObject $task -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName

@{
    installed = $true
    task_name = $TaskName
    user = $identity
    project_root = $resolvedRoot
    secret_protection = "Windows DPAPI current user"
} | ConvertTo-Json -Compress
