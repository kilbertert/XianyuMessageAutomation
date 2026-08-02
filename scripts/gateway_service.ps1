[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectRoot,

    [string]$ConfigPath = "config.json",
    [string]$SecretPath = "var\service\gateway-secret.dpapi",
    [string]$LogPath = "var\service\gateway.log"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$resolvedRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$resolvedConfig = if ([IO.Path]::IsPathRooted($ConfigPath)) {
    $ConfigPath
} else {
    Join-Path $resolvedRoot $ConfigPath
}
$resolvedSecret = if ([IO.Path]::IsPathRooted($SecretPath)) {
    $SecretPath
} else {
    Join-Path $resolvedRoot $SecretPath
}
$resolvedLog = if ([IO.Path]::IsPathRooted($LogPath)) {
    $LogPath
} else {
    Join-Path $resolvedRoot $LogPath
}
$gatewayCli = Join-Path $resolvedRoot ".venv\Scripts\xianyu-msg.exe"

foreach ($requiredPath in @($resolvedConfig, $resolvedSecret, $gatewayCli)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "Required gateway file is missing: $requiredPath"
    }
}

$logDirectory = Split-Path -Parent $resolvedLog
[IO.Directory]::CreateDirectory($logDirectory) | Out-Null

function Rotate-GatewayLog {
    if ((Test-Path -LiteralPath $resolvedLog -PathType Leaf) -and
        (Get-Item -LiteralPath $resolvedLog).Length -ge 10MB) {
        $archivePath = "$resolvedLog.1"
        if (Test-Path -LiteralPath $archivePath -PathType Leaf) {
            [IO.File]::Delete($archivePath)
        }
        [IO.File]::Move($resolvedLog, $archivePath)
    }
}

function Write-GatewayServiceEvent {
    param(
        [Parameter(Mandatory = $true)]
        [string]$EventName,
        [hashtable]$Data = @{}
    )

    $record = @{
        timestamp = [DateTimeOffset]::Now.ToString("o")
        event = $EventName
    }
    foreach ($entry in $Data.GetEnumerator()) {
        $record[$entry.Key] = $entry.Value
    }
    Add-Content -LiteralPath $resolvedLog -Value ($record | ConvertTo-Json -Compress) -Encoding UTF8
}

$secretPointer = [IntPtr]::Zero
try {
    $encryptedSecret = (Get-Content -LiteralPath $resolvedSecret -Raw).Trim()
    $secureSecret = ConvertTo-SecureString $encryptedSecret
    $secretPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureSecret)
    $env:ANDROID_GATEWAY_SHARED_SECRET = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($secretPointer)

    Set-Location -LiteralPath $resolvedRoot
    while ($true) {
        Rotate-GatewayLog
        Write-GatewayServiceEvent -EventName "gateway_starting"
        $exitCode = -1
        try {
            & $gatewayCli --config $resolvedConfig gateway --interval 0.5 *>> $resolvedLog
            $exitCode = $LASTEXITCODE
        } catch {
            Write-GatewayServiceEvent -EventName "gateway_exception" -Data @{
                type = $_.Exception.GetType().FullName
            }
        }
        Write-GatewayServiceEvent -EventName "gateway_stopped" -Data @{ exit_code = $exitCode }
        Start-Sleep -Seconds 10
    }
} finally {
    Remove-Item Env:ANDROID_GATEWAY_SHARED_SECRET -ErrorAction SilentlyContinue
    if ($secretPointer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($secretPointer)
    }
}
