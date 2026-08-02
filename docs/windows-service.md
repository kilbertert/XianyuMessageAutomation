# Windows persistent gateway

The Android gateway uses a supervised Scheduled Task instead of a Session 0 Windows service.
ADB and UI automation need the logged-in user's interactive desktop session, so the task starts at
that user's logon and remains invisible in the background.

## Install

Run PowerShell as the same Windows user who owns the ADB session:

```powershell
$secret = Read-Host "Android gateway shared secret" -AsSecureString
.\scripts\install_gateway_service.ps1 -SharedSecret $secret
```

The installer:

- verifies `config.json` and `.venv\Scripts\xianyu-msg.exe`;
- stores the shared secret with Windows DPAPI for the current user;
- restricts `var\service` to the current user and `SYSTEM`;
- registers `XianyuAndroidMessageGateway` at user logon;
- remains active when the Windows host is running on battery power;
- restarts the gateway after either an unexpected process exit or a task failure.

The secret is decrypted only inside the supervisor process and inherited by the gateway child
process as `ANDROID_GATEWAY_SHARED_SECRET`. It is never placed in the Scheduled Task command line.

## Inspect

```powershell
Get-ScheduledTask -TaskName XianyuAndroidMessageGateway
Get-ScheduledTaskInfo -TaskName XianyuAndroidMessageGateway
Get-Content .\var\service\gateway.log -Tail 50
```

The log rotates at 10 MiB and keeps one archive. It is inside the private `var\service` directory
and is not committed to Git. Because the gateway's own output is captured there, treat the log as
sensitive operational data.

## Uninstall

```powershell
.\scripts\uninstall_gateway_service.ps1
```

Add `-PurgeSecret` to remove the DPAPI-protected secret as well. The command targets only this
task and this repository's exact secret file.

## Runtime requirements

- the configured Android phone is connected and authorized for ADB;
- the Windows user is logged in;
- the phone remains unlocked when Xianyu UI interaction is expected;
- the server gateway health endpoint is reachable through Tailscale.

The task intentionally does not run before user logon: a background Session 0 process cannot
reliably interact with the phone UI and keyboard flow used by this gateway.
