# Windows 常驻服务

项目使用“交互式用户计划任务 + PowerShell 监督器”，而不是传统 Windows Service。
ADB 和闲鱼 UI 自动化依赖已登录用户的交互式会话，Session 0 不能可靠完成输入法和页面操作。

## 1. 组成

```text
Windows Task Scheduler
  XianyuAndroidMessageGateway
    -> powershell.exe scripts/gateway_service.ps1
         -> xianyu-msg.exe gateway --interval 0.5 --supervisor-pid <PID> [--include-existing]
              -> Python gateway process
```

计划任务在当前用户登录时启动。监督器负责：

- 从当前用户 DPAPI 文件解密共享密钥；
- 只在子进程环境中设置 `ANDROID_GATEWAY_SHARED_SECRET`；
- 启动网关；
- 把监督器 PID 传给网关，监督器退出后子进程自行停止；
- 子进程退出后等待 10 秒再启动；
- 记录启动、停止和异常事件；
- 日志达到 10 MiB 时轮转一份归档。

## 2. 安装前提

- 在与 ADB 授权相同的 Windows 用户下操作；
- `config.json` 已完成；
- `.venv\Scripts\xianyu-msg.exe` 已安装；
- AdbKeyboard 已有人值守安装；
- 服务器健康接口 `enabled=true`；
- 没有另一个手工 `gateway` 进程。

## 3. 安装或更新

```powershell
$secret = Read-Host "Android gateway shared secret" -AsSecureString
.\scripts\install_gateway_service.ps1 -SharedSecret $secret
```

安装器会：

- 验证监督脚本、CLI 和配置文件；
- 创建 `var/service`；
- 将 ACL 限制为当前用户和 `SYSTEM` 的完全控制；
- 使用当前用户 DPAPI 写入 `gateway-secret.dpapi`；
- 注册登录触发的 `XianyuAndroidMessageGateway`；
- 使用 `Interactive`、`Limited` 用户主体运行；
- 允许电池供电时启动和继续运行；
- 禁止执行时限；
- 忽略重复任务实例；
- 配置计划任务失败后的每分钟重启；
- 立即启动任务。

脚本可重复执行，用于更新任务定义或替换密钥。它不会把明文密钥放入任务命令行。

成功输出示例：

```json
{
  "installed": true,
  "task_name": "XianyuAndroidMessageGateway",
  "secret_protection": "Windows DPAPI current user"
}
```

## 4. 检查状态

```powershell
Get-ScheduledTask -TaskName XianyuAndroidMessageGateway
Get-ScheduledTaskInfo -TaskName XianyuAndroidMessageGateway
Get-Content .\var\service\gateway.log -Tail 50
```

正常结果：

- `State` 是 `Running`；
- `LastTaskResult` 可能是 `267009` / `0x41301`，表示任务仍在运行；
- 日志最近有 `gateway_starting`，没有持续重复的异常。

检查监督器与子进程：

```powershell
Get-CimInstance Win32_Process |
  Where-Object {
    $_.CommandLine -match 'gateway_service\.ps1' -or
    $_.CommandLine -match 'XianyuMessageAutomation.*gateway'
  } |
  Select-Object ProcessId,ParentProcessId,Name,CommandLine
```

期望一个 PowerShell 根监督器和一条 `xianyu-msg/python` 父子链。

网关同时持有状态文件旁的 OS 锁。即使计划任务的“忽略重复实例”或人工操作失效，第二个
`gateway` 也会以退出码 2 拒绝启动；锁由进程所有权控制，崩溃后不需要人工删除。

## 5. 通知基线和重启重放

首次启动时，如果 `gateway.notification_state_file` 尚不存在，CLI 不带
`--include-existing`，当前活动通知只作为安全基线，不会回复启动前的历史消息。

状态文件一旦存在，监督器的每次子进程启动都会添加 `--include-existing`。这样：

- 尚未确认、仍在通知栏的通知会在进程重启后重试；
- 已经写入通知账本的通知不会重复路由；
- 新安装不会突然处理一批历史通知。

不要手工删除通知状态文件来强制重放。只有在停止全部网关进程、精确识别目标指纹并评估
重复回复风险后，才能进行受控状态修复。

## 6. 日志与权限

```text
var/service/gateway.log
var/service/gateway.log.1
var/service/gateway-secret.dpapi
```

日志包含监督器 JSON 事件和网关 stdout/stderr，可能出现聊天正文或发送者标签。目录被 Git
忽略并限制 ACL，但仍应作为敏感数据处理。

查看 ACL：

```powershell
Get-Acl .\var\service | Format-List
```

不要复制 DPAPI 文件到另一台机器或另一位用户。它只能由创建它的 Windows 用户解密。

## 7. 启停

```powershell
Start-ScheduledTask -TaskName XianyuAndroidMessageGateway
Stop-ScheduledTask -TaskName XianyuAndroidMessageGateway
```

重启：

```powershell
Stop-ScheduledTask -TaskName XianyuAndroidMessageGateway
Start-Sleep -Seconds 2
Start-ScheduledTask -TaskName XianyuAndroidMessageGateway
```

新版本子进程会在监督器 PID 消失后自行退出。如果停止后仍有旧版本遗留子进程，不要按名称
结束所有 Python；先用完整命令行和父进程关系确认只属于本仓库，再结束精确 PID。

## 8. 运行要求

- Windows 用户已经登录；
- 手机保持 ADB 授权和 `device` 状态；
- 需要处理消息时手机可解锁操作；
- 闲鱼位于后台以产生通知；
- Tailscale 和 9090 健康；
- 系统输入法和 AdbKeyboard 都未被禁用。

任务故意不在用户登录前运行。把它改成 `SYSTEM` 或 Session 0 服务不会得到等价可靠性。

## 9. 卸载

保留加密密钥：

```powershell
.\scripts\uninstall_gateway_service.ps1
```

同时删除 DPAPI 密钥：

```powershell
.\scripts\uninstall_gateway_service.ps1 -PurgeSecret
```

卸载脚本只操作指定任务和本仓库精确密钥文件，不删除配置、状态、队列或日志。

## 10. 安全注意

- 共享密钥不应出现在脚本参数、Git、日志或截图；
- 安装器输入使用 `SecureString`，但用户仍应避免在录屏中暴露输入；
- 不要把任务改为多个实例并行；
- 不要在任务运行中手工启动网关；
- 密钥轮换后必须同时更新服务器并重装任务；
- `send_unconfirmed` 必须按人工事件处理，不能通过重启任务强制重发。
