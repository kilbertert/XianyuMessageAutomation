# Xianyu Message Automation

用于自有闲鱼账号消息接收与安全回复的 Android 自动化工程。

当前版本把已经在真机验证的链路固化为可测试的 MVP：

- ADB、设备和小米输入权限检查；
- 闲鱼未读数量读取；
- 闲鱼系统通知增量监控与本地 JSONL 事件流；
- 通知唯一定位、精确会话打开与最新入站正文队列；
- 待处理队列租约领取、显式确认、失败重试与死信；
- 消息列表截图与会话行校准；
- 聊天正文 marker 唯一校验；
- 默认 dry-run；
- 显式 `--apply` 后只发送一次；
- 发送后消息气泡确认；
- 哈希去重与原子状态文件。

首版不做陌生人群发、自动营销、支付、下单或风控绕过，也不宣称已经支持无人值守扫描所有会话。

## 环境

- Windows
- Python 3.11+
- Android 设备
- ADB
- 闲鱼 `com.taobao.idlefish`
- 已开启“USB 调试”和“USB 调试（安全设置）”

## 安装

```powershell
cd D:\AI\job\XianyuMessageAutomation
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item config.example.json config.json
```

## 使用

检查设备：

```powershell
.\.venv\Scripts\xianyu-msg.exe --config config.json doctor
```

读取未读数：

```powershell
.\.venv\Scripts\xianyu-msg.exe --config config.json unread
```

持续识别新的闲鱼通知：

```powershell
.\.venv\Scripts\xianyu-msg.exe --config config.json monitor `
  --interval 0.5
```

监控启动时会把已有通知作为基线，只输出之后出现或更新的通知。调试当前活动通知时，
可使用 `monitor --once --include-existing`。默认仅输出交易聊天消息；排查其他闲鱼通知时
显式增加 `--all-notifications`。监控只识别和记录事件，不会打开聊天或发送回复。

持续把新消息正文写入待处理队列：

```powershell
.\.venv\Scripts\xianyu-msg.exe --config config.json inbox `
  --interval 0.5
```

`inbox` 会以现有通知建立基线。之后出现聊天通知时，它要求发送者标题唯一，打开对应
聊天、提取最新左侧入站气泡、写入 `var/inbound-pending.jsonl`，再返回桌面。整个流程
不输入文字、不点击发送；打开聊天会把会话标记为已读。

消费最早一条待处理消息，并获得 5 分钟租约：

```powershell
.\.venv\Scripts\xianyu-msg.exe --config config.json queue claim `
  --worker-id reply-policy-1 `
  --lease-seconds 300
```

处理成功后必须由同一个 worker 显式确认：

```powershell
.\.venv\Scripts\xianyu-msg.exe --config config.json queue ack `
  --worker-id reply-policy-1 `
  --fingerprint MESSAGE_SHA256
```

处理失败时释放重试；达到最大次数后进入死信：

```powershell
.\.venv\Scripts\xianyu-msg.exe --config config.json queue fail `
  --worker-id reply-policy-1 `
  --fingerprint MESSAGE_SHA256 `
  --reason "downstream unavailable" `
  --max-attempts 3
```

未确认的租约到期后会重新投递，因此下游处理必须保持幂等。消费状态只保存指纹、租约、
次数和失败原因哈希；正文仍只存在于 Git 忽略的 `var/inbound-pending.jsonl`。

保存消息列表截图，用于读取目标会话行中心的 Y 坐标：

```powershell
.\.venv\Scripts\xianyu-msg.exe --config config.json screenshot-list `
  --output var\message-list.png
```

先进行 dry-run：

```powershell
.\.venv\Scripts\xianyu-msg.exe --config config.json reply `
  --marker AUTO_E2E_001 `
  --reply "收到，这是自动化联调测试。" `
  --conversation-y 925
```

只有返回 `dry_run_ready` 后才执行真实发送：

```powershell
.\.venv\Scripts\xianyu-msg.exe --config config.json reply `
  --marker AUTO_E2E_001 `
  --reply "收到，这是自动化联调测试。" `
  --conversation-y 925 `
  --apply
```

如果已经人工打开目标聊天，可用 `--current-chat` 替代 `--conversation-y`。

## 状态

`var/state.json` 只保存 marker/会话提示的 SHA-256 指纹、发送时间和回复哈希，不保存聊天正文。
通知去重状态同样只保存哈希；`var/inbound-notifications.jsonl` 会保存通知标题和正文，
仅用于本机消息路由，整个 `var/` 目录不会提交到 Git。
`var/inbound-pending.jsonl` 保存已提取的待处理消息正文；对应状态文件只保存哈希。
`var/inbound-consumer-state.json` 保存领取、完成和死信生命周期，不复制发送者或正文。

重要状态：

- `dry_run_ready`：目标唯一且没有回复，可以人工决定是否发送；
- `sent`：只点击一次发送，并在页面确认到唯一回复气泡；
- `skipped_duplicate`：页面或状态文件表明已经处理；
- `target_missing` / `target_not_unique`：拒绝发送；
- `send_unconfirmed`：已点击一次但页面未确认，立即停止，不自动重试。

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest
```

架构与设备校准说明见：

- [Architecture](docs/architecture.md)
- [Device calibration](docs/device-calibration.md)
- [Inbound detection](docs/inbound-detection.md)
- [Validation record](docs/validation.md)

## 合规与隐私

本项目只面向自有账号的授权工作流。请遵守闲鱼服务协议，不用于群发、骚扰、
欺诈、抓取他人隐私或规避平台限制。聊天截图可能包含个人信息，默认不保留；
只有显式传入 `--keep-artifacts` 才会写入 `var/artifacts/`，该目录不会提交到 Git。
