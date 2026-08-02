# 配置说明

运行配置位于仓库根目录的 `config.json`。该文件由 `config.example.json` 复制得到，并被
`.gitignore` 排除。不要把设备序列号、服务器账号 ID 或其他私有运行信息写回模板。

```powershell
Copy-Item config.example.json config.json
```

相对路径都以 `config.json` 所在目录为基准解析。

## 顶层字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `serial` | string | `adb devices` 中的设备序列号，不能为空 |
| `adb_path` | string | ADB 可执行文件，默认使用 PATH 中的 `adb` |
| `state_file` | path | 手工 `reply` 模式的去重状态 |
| `artifact_dir` | path | 显式保留截图时的目录 |
| `app` | object | 闲鱼包名和 Activity |
| `coordinates` | object | 自绘 UI 的比例坐标 |
| `timings` | object | 页面、输入和确认等待时间 |
| `notifications` | object | 只读通知监控配置 |
| `inbound` | object | 本地待处理队列配置 |
| `gateway` | object | 9090 生产网关配置 |
| `delete_key_count` | integer | 输入前补充发送的删除键次数，必须非负 |

## app

| 字段 | 当前值 | 用途 |
|---|---|---|
| `package` | `com.taobao.idlefish` | 过滤通知、检查前台和启动 App |
| `main_activity` | `.maincontainer.activity.MainActivity` | 闲鱼主页面标识 |
| `chat_activity` | `com.idlefish.flutterbridge.flutterboost.boost.FishFlutterBoostActivity` | 验证已进入聊天页 |

闲鱼升级后 Activity 名称可能变化。出现“expected chat activity”错误时，先用
`adb shell dumpsys window` 验证，而不是直接改坐标。

## coordinates

除 `conversation_y` 由 `reply` 命令单独传入像素值外，配置中的坐标都是 0 到 1 的屏幕
比例。

| 字段 | 示例 | 用途 |
|---|---:|---|
| `message_tab` | `[0.705, 0.953]` | 消息 Tab 中心 |
| `conversation_x` | `0.463` | 手工会话行点击的横向比例 |
| `input` | `[0.463, 0.942]` | 聊天输入框中心 |
| `candidate_commit` | `[0.417, 0.640]` | 保留兼容字段；当前网关使用 AdbKeyboard，不再依赖候选词点击 |
| `send` | `[0.899, 0.953]` | AdbKeyboard 收起后的黄色发送按钮 |

示例坐标只对已验证设备提供起点，不是跨设备常量。校准流程见
[设备准备与坐标校准](device-calibration.md)。

## timings

| 字段 | 示例 | 说明 |
|---|---:|---|
| `app_start_seconds` | `5.0` | 启动闲鱼后等待 |
| `page_seconds` | `5.0` | 页面切换和通知栏渲染等待基础值 |
| `input_seconds` | `2.0` | 输入框聚焦和文本提交等待 |
| `send_timeout_seconds` | `12.0` | 等待回复气泡出现在可访问性树中的时间 |
| `poll_seconds` | `0.75` | UI 状态轮询间隔 |

网关在 `send_timeout_seconds` 后还会尝试按唯一会话标题退出并重开一次聊天，以刷新 Flutter
可访问性树。不要通过大幅缩短等待时间来追求速度；这会把成功发送误判成
`send_unconfirmed`。

## notifications

| 字段 | 说明 |
|---|---|
| `state_file` | `monitor` 的通知去重账本 |
| `event_log` | `monitor` 输出的 JSONL 文件，可能含通知文字 |
| `poll_seconds` | 默认通知轮询间隔，必须大于 0 |
| `message_channel_ids` | 允许作为聊天消息处理的完整通知频道 ID 列表 |

当前验证频道：

```text
mipush|com.taobao.idlefish|107787
```

如果闲鱼升级后消息完全无法检测，可使用
`monitor --once --include-existing --all-notifications` 诊断频道变化，然后在确认“交易聊天
消息”对应的新频道后修改白名单。不要在生产中长期启用 `--all-notifications`。

## inbound

这组配置只服务于独立的本地 `inbox / queue` 模式，不是生产同步回复主链路。

| 字段 | 说明 |
|---|---|
| `notification_state_file` | `inbox` 已确认通知指纹 |
| `queue_state_file` | `inbox` 入队去重状态 |
| `queue_file` | 追加写入的待处理消息 JSONL，含正文 |
| `consumer_state_file` | `queue` 的租约、尝试次数、完成与死信状态 |

这些路径应位于 Git 忽略的 `var/` 下。

## gateway

| 字段 | 必填 | 说明 |
|---|---:|---|
| `base_url` | 是 | 9090 后台地址，无末尾 `/` |
| `account_id` | 是 | 9090 账号管理中的 Cookie ID |
| `device_id` | 是 | 设备稳定名称，用于事件审计 |
| `shared_secret_env` | 是 | 读取共享密钥的环境变量名 |
| `state_file` | 是 | 崩溃恢复与完成事件账本 |
| `notification_state_file` | 是 | 网关已确认通知账本 |
| `request_timeout_seconds` | 是 | 单次 HTTP 请求超时，必须大于 0 |
| `max_attempts` | 是 | 5xx/网络错误的请求尝试次数，必须大于 0 |

`base_url` 安全约束：

- HTTPS 地址允许；
- `localhost`、`127.0.0.1`、`::1` 的 HTTP 允许；
- Tailscale `100.64.0.0/10` 地址的 HTTP 允许；
- 其他普通公网 HTTP 地址被客户端拒绝。

共享密钥不写在 JSON 中。手工运行时：

```powershell
$env:ANDROID_GATEWAY_SHARED_SECRET = "与服务器相同的随机密钥"
.\.venv\Scripts\xianyu-msg.exe --config config.json gateway --interval 0.5
```

常驻任务使用 DPAPI 文件注入该环境变量，见 [Windows 常驻服务](windows-service.md)。

## 服务器环境变量

服务器 `xianyu-auto-reply-fix` 需要：

```dotenv
ANDROID_GATEWAY_SHARED_SECRET=与Windows端完全相同
ANDROID_GATEWAY_ACCOUNT_IDS=一个或多个Cookie ID，用逗号分隔
```

`ANDROID_GATEWAY_ACCOUNT_IDS` 同时表示这些账号的收发由 Android 网关接管。服务器会跳过
它们的旧 WebSocket 自动回复任务，防止重复发送。

## 配置检查

加载配置和检查设备：

```powershell
.\.venv\Scripts\xianyu-msg.exe --config config.json doctor
```

检查后台地址：

```powershell
$config = Get-Content .\config.json -Raw | ConvertFrom-Json
Invoke-RestMethod "$($config.gateway.base_url)/api/android-gateway/v1/health"
```

检查 JSON 语法但不输出内容：

```powershell
Get-Content .\config.json -Raw | ConvertFrom-Json | Out-Null
```

## 不要做的操作

- 不要提交 `config.json`；
- 不要把共享密钥写进配置、脚本、日志或命令历史；
- 不要让 `state_file` 和 `notification_state_file` 指向同一个文件；
- 不要在事件处于 `pending` 时删除 `gateway-state.json`；
- 不要复制另一台手机的坐标后跳过真机验收；
- 不要为同一账号启动多个 `gateway` 实例。
