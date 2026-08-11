# 从零开始

本手册面向第一次部署该项目的人。完成后，你应该能够让第二个自有闲鱼账号发出一条测试
消息，并在 9090 后台获得决策、由 Android 自动回复、最终看到 `sent` 回执。

## 1. 部署前确认

### Windows 端

- Windows 10/11，使用日常登录的普通用户；
- Python 3.11+；
- Git；
- Android Platform Tools，`adb version` 可执行；
- Tailscale 已连接，能够访问 9090 后台。

### Android 端

- 已安装并登录闲鱼；
- USB 调试已开启；
- “USB 调试（安全设置）”已开启；
- 已通过 USB 或稳定的 ADB 网络连接到 Windows；
- 闲鱼通知权限和交易聊天通知频道已开启；
- 首次安装输入法时可以在手机上人工确认 APK 安装。

### 服务器端

- `xianyu-auto-reply-fix` 正在运行；
- 目标账号已在 9090“账号管理”中导入有效 Cookie；
- 你知道该账号对应的 Cookie ID；
- 服务器与 Windows 使用同一个 Android 网关共享密钥。

## 2. 克隆和安装

```powershell
git clone https://github.com/kilbertert/XianyuMessageAutomation.git
cd XianyuMessageAutomation
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

确认 CLI 可用：

```powershell
.\.venv\Scripts\xianyu-msg.exe --help
```

## 3. 连接手机

在手机上接受这台电脑的调试授权，然后执行：

```powershell
adb devices
```

正确输出应包含一行：

```text
设备序列号    device
```

如果状态是 `unauthorized`、`offline` 或设备没有出现，先按
[故障排查](troubleshooting.md#adb-看不到手机或状态不是-device)处理，不要继续安装常驻任务。

## 4. 安装 AdbKeyboard

闲鱼的 Flutter 输入框不能稳定使用普通 `adb shell input text`。项目使用 uiautomator2
提供的 AdbKeyboard 精确写入文本。

```powershell
.\.venv\Scripts\python.exe -c "import uiautomator2 as u2; u2.connect('设备序列号').set_input_ime(True)"
```

第一次执行时：

1. 手机会出现 APK 安装弹窗；
2. 在手机上同意安装；
3. 等待命令结束；
4. 确认输入法已经存在。

```powershell
adb -s 设备序列号 shell ime list -s
```

列表应包含：

```text
com.github.uiautomator/.AdbKeyboard
```

可以立即切回原输入法：

```powershell
adb -s 设备序列号 shell ime set 你的原输入法ID
```

正式发送时程序会记住当前输入法、临时切换 AdbKeyboard，并在完成输入后恢复原输入法。

## 5. 创建私有配置

```powershell
Copy-Item config.example.json config.json
```

至少修改以下三项：

```json
{
  "serial": "adb devices 中的序列号",
  "gateway": {
    "base_url": "http://服务器的Tailscale地址:9090",
    "account_id": "9090后台中的Cookie ID",
    "device_id": "android-primary"
  }
}
```

不要把上面的片段单独覆盖整个文件；在完整的 `config.json` 中修改对应值。坐标和其他字段见
[配置说明](configuration.md)。

运行设备自检：

```powershell
.\.venv\Scripts\xianyu-msg.exe --config config.json doctor
```

期望输出示例：

```json
{
  "ok": true,
  "serial": "...",
  "input_injection": true,
  "package": "com.taobao.idlefish",
  "version_name": "7.19.70"
}
```

版本不同不一定失败，但必须重新执行坐标和端到端验收。

## 6. 配置 9090 后台

在服务器项目 `xianyu-auto-reply-fix` 的 `.env` 中设置：

```dotenv
ANDROID_GATEWAY_SHARED_SECRET=一个足够长的随机密钥
ANDROID_GATEWAY_ACCOUNT_IDS=目标账号的Cookie ID
```

多个账号使用逗号分隔。重新创建服务，使环境变量进入容器：

```bash
docker compose up -d --force-recreate
```

服务器本机检查：

```bash
curl http://127.0.0.1:9090/api/android-gateway/v1/health
```

Windows 端检查实际地址：

```powershell
Invoke-RestMethod http://服务器的Tailscale地址:9090/api/android-gateway/v1/health
```

正确结果：

```json
{"ok":true,"enabled":true,"service":"android-message-gateway"}
```

`enabled: false` 表示服务进程没有获得共享密钥。完整后台说明见
[9090 后台对接](server-gateway.md)。

## 7. 先做只读通知测试

确保闲鱼位于后台、手机停留在桌面，然后运行：

```powershell
.\.venv\Scripts\xianyu-msg.exe --config config.json monitor --duration 60 --interval 0.5
```

从另一个自有账号发送一条唯一测试消息。预期 stdout 出现一条
`"type": "xianyu_message"` 事件。`monitor` 只读取通知，不打开聊天也不发送消息。

如果消息已经发出、通知当前仍在通知栏，可做一次受控诊断：

```powershell
.\.venv\Scripts\xianyu-msg.exe --config config.json monitor --once --include-existing
```

不要把 `--include-existing` 作为多个并发进程的常规启动方式。

## 8. 校准设备

示例坐标来自 1080 × 2400 的小米 13 和闲鱼 7.19.70。设备、分辨率、字体、系统版本、
闲鱼版本或输入布局不同，都要按[设备准备与坐标校准](device-calibration.md)重新确认。

最小检查：

```powershell
.\.venv\Scripts\xianyu-msg.exe --config config.json screenshot-list `
  --output var\message-list.png
```

使用 `reply` 命令时先 dry-run，只有 `dry_run_ready` 才加 `--apply`。生产 `gateway` 不依赖
消息列表行坐标，但仍依赖输入框和发送按钮坐标。

## 9. 安装常驻任务

共享密钥必须与服务器完全一致：

```powershell
$secret = Read-Host "Android gateway shared secret" -AsSecureString
.\scripts\install_gateway_service.ps1 -SharedSecret $secret
```

安装成功后检查：

```powershell
Get-ScheduledTask -TaskName XianyuAndroidMessageGateway | Format-List TaskName,State
Get-ScheduledTaskInfo -TaskName XianyuAndroidMessageGateway
Get-Content .\var\service\gateway.log -Tail 50
```

任务状态应为 `Running`。`LastTaskResult` 为 `267009`（十六进制 `0x41301`）时表示任务当前
仍在运行，不是失败码。

首次运行会把已经存在的通知作为基线。此时先保持手机桌面状态，再从另一个账号发送新的
测试消息。

## 10. 完成第一次真实验收

1. 在 9090 后台为目标账号配置一个可预测的临时关键词回复；
2. 手机解锁并回到桌面，闲鱼留在后台；
3. 从另一个自有账号发送唯一关键词；
4. 不要人工打开通知、切换闲鱼或点击发送；
5. 等待约 30 秒；
6. 查看 `var/service/gateway.log` 和 9090 后台事件；
7. 人工打开目标聊天，只读确认入站消息和回复各一条；
8. 删除临时关键词规则。

通过标准：

- Android 输出一个新的 `event_id`；
- 事件正文与发送内容一致；
- 后台决策 `action=reply` 且文本正确；
- Android 结果为 `sent`、`sent_clicks=1`；
- 服务器事件表存在 `receipt_outcome=sent` 和非空 `receipt_applied_at`；
- 聊天页只有一条精确回复；
- 手机最后回到桌面，原输入法已经恢复；
- 常驻任务仍为 `Running`。

注意：回复气泡显示“未读”只表示对方尚未阅读，不影响 `sent` 验收。

## 11. 下一步

- 日常启动、升级和日志检查：[日常运维](operations.md)
- 所有配置字段：[配置说明](configuration.md)
- 失败状态与恢复：[故障排查](troubleshooting.md)
- 已验证环境和证据：[验收手册与记录](validation.md)
