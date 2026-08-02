# 日常运维

生产模式使用 Windows 计划任务 `XianyuAndroidMessageGateway`。本手册假设已经完成
[从零开始](getting-started.md)中的安装和真实消息验收。

## 1. 正常运行条件

每天运行需要同时满足：

- Windows 用户保持登录；
- 手机 ADB 状态为 `device`；
- 手机已解锁，闲鱼位于后台，屏幕最终停留在桌面；
- 闲鱼交易聊天通知权限正常；
- Tailscale 已连接；
- 9090 健康接口返回 `enabled: true`；
- 目标账号 Cookie 仍有效；
- 只存在一个计划任务监督器和一个网关进程链。

推荐让手机保持充电，并按实际设备策略关闭会杀死闲鱼通知或 USB 调试的省电限制。

## 2. 每日快速检查

```powershell
adb devices
Get-ScheduledTask -TaskName XianyuAndroidMessageGateway | Format-List TaskName,State
Get-ScheduledTaskInfo -TaskName XianyuAndroidMessageGateway
Get-Content .\var\service\gateway.log -Tail 30
$config = Get-Content .\config.json -Raw | ConvertFrom-Json
Invoke-RestMethod "$($config.gateway.base_url)/api/android-gateway/v1/health"
```

健康状态：

- ADB 列表中目标序列号为 `device`；
- 任务为 `Running`；
- `LastTaskResult=267009`（`0x41301`）表示任务仍在运行；
- 日志没有循环出现相同异常；
- 健康接口返回 `ok=true`、`enabled=true`。

## 3. 启动、停止和重启

启动：

```powershell
Start-ScheduledTask -TaskName XianyuAndroidMessageGateway
```

停止：

```powershell
Stop-ScheduledTask -TaskName XianyuAndroidMessageGateway
```

重启：

```powershell
Stop-ScheduledTask -TaskName XianyuAndroidMessageGateway
Start-Sleep -Seconds 2
Start-ScheduledTask -TaskName XianyuAndroidMessageGateway
```

重启后检查命令行中存在 `--include-existing`：

```powershell
Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -match 'XianyuMessageAutomation.*gateway' } |
  Select-Object ProcessId,ParentProcessId,Name,CommandLine
```

第一次从未运行过且通知状态文件不存在时不会带该参数，这是安全基线行为。状态文件存在后的
监督器重启会处理仍在通知栏、尚未确认的通知。

不要在计划任务运行时再手工执行 `xianyu-msg gateway`。

## 4. 进程模型

正常情况下可以看到：

- 1 个运行 `scripts/gateway_service.ps1` 的 PowerShell 监督器；
- `xianyu-msg.exe → python.exe → python.exe` 的启动链。

三个网关相关进程是 Windows Python 启动器的父子链，不表示处理了三次消息。真正需要警惕
的是出现多个 `gateway_service.ps1` 根监督器，或多个不属于同一父子链的网关实例。

停止任务后如果仍能看到旧进程，不要按模糊名称结束所有 Python。先通过完整命令行和
`ParentProcessId` 确认它们属于本仓库，再结束精确 PID。误杀其他 Python 进程可能影响用户
的其他项目。

## 5. 日志

日志位置：

```text
var/service/gateway.log
```

查看最新内容：

```powershell
Get-Content .\var\service\gateway.log -Tail 100 -Wait
```

监督器在日志达到 10 MiB 时轮转为 `gateway.log.1`，只保留一份归档。日志可能包含发送者
标签、正文或后台决策，应按聊天数据保护。

常见监督器事件：

- `gateway_starting`：准备启动 CLI；
- `gateway_stopped`：CLI 已退出，10 秒后重启；
- `gateway_exception`：监督器捕获到启动或执行异常。

CLI 事件中的 `status`：

| 状态 | 含义 | 运维动作 |
|---|---|---|
| `sent` | 新回复气泡已确认，回执完成 | 无 |
| `no_reply` | 后台决定不回复 | 核对规则是否符合预期 |
| `skipped_duplicate` | 本地已完成同一事件 | 无 |
| `unsupported` | 当前不支持该决策，通常是图片 | 人工处理 |
| `send_unconfirmed` | 最多点击一次后无法确认 | 立即人工检查聊天，禁止自动重发 |

## 6. 状态文件运维

生产主路径使用：

- `var/gateway-notification-state.json`：已确认通知指纹；
- `var/gateway-state.json`：一个 pending 事件和已完成摘要；
- `var/service/gateway-secret.dpapi`：当前 Windows 用户加密的共享密钥。

查看状态时先停止可能正在写入的任务，或只做原子读取：

```powershell
Get-Content .\var\gateway-state.json -Raw | ConvertFrom-Json
Get-Content .\var\gateway-notification-state.json -Raw | ConvertFrom-Json
```

不要为了“重新跑一条消息”直接删除状态文件。若状态显示 `sending`，删除后重试可能导致
重复回复。正确处理方式见
[故障排查](troubleshooting.md#发送后没有新气泡或出现-send_unconfirmed)。

## 7. 升级代码

升级前确保没有正在处理的消息：

```powershell
Stop-ScheduledTask -TaskName XianyuAndroidMessageGateway
git status --short --branch
git pull --ff-only
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest -q
Start-ScheduledTask -TaskName XianyuAndroidMessageGateway
```

然后检查：

```powershell
Get-ScheduledTask -TaskName XianyuAndroidMessageGateway
Get-Content .\var\service\gateway.log -Tail 50
```

升级没有自动修改 `config.json`。对比 `config.example.json` 的新字段，并按
[配置说明](configuration.md)手工迁移。不要用模板覆盖私有配置。

若变更了 `scripts/install_gateway_service.ps1` 或 DPAPI 逻辑，可使用相同密钥重新运行安装器；
脚本设计为幂等更新任务和权限。

## 8. 更换手机或闲鱼版本

1. 停止计划任务；
2. 更新 `config.json.serial`；
3. 在新手机上完成 USB 调试授权和 AdbKeyboard 安装；
4. 运行 `doctor`；
5. 重新校准坐标；
6. 运行一条完整 E2E；
7. 验收通过后再恢复常驻任务。

不要直接沿用旧设备坐标进入无人值守运行。

## 9. 后台变更

更换后台地址：修改 `gateway.base_url` 后重启任务。

更换共享密钥：

1. 停止任务；
2. 更新服务器 `.env` 并重建 Compose 服务；
3. 用新密钥重新运行 `install_gateway_service.ps1`；
4. 检查健康接口和真实 E2E。

更换账号：同时更新：

- 9090 中有效 Cookie；
- 服务器 `ANDROID_GATEWAY_ACCOUNT_IDS`；
- Android `config.json.gateway.account_id`；
- 手机闲鱼登录账号。

四处必须指向同一自有账号。

## 10. 数据备份和清理

需要保留审计证据时，可在任务停止后备份整个 `var/` 到受控私有位置。它可能包含聊天正文，
不要放入 Git、公开网盘或普通工单附件。

可以定期清理旧截图，但必须先确认不是正在处理的事件证据。日志由监督器自动轮转。不要在
运行中清空 `gateway-state.json` 或通知账本。

## 11. 卸载

保留 DPAPI 密钥：

```powershell
.\scripts\uninstall_gateway_service.ps1
```

同时删除本仓库保存的 DPAPI 密钥：

```powershell
.\scripts\uninstall_gateway_service.ps1 -PurgeSecret
```

卸载只针对指定计划任务和本仓库的密钥文件，不删除 `config.json`、日志或消息状态。

## 12. 发布前回归

每次更改通知解析、输入、发送、恢复、服务脚本或后台协议后，至少完成：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\xianyu-msg.exe --config config.json doctor
```

高风险变更还必须执行[验收手册](validation.md)中的真实
`event → reply → sent receipt` 流程。
