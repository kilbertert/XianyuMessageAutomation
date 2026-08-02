# 9090 后台对接

后台仓库位于服务器的 `xianyu-auto-reply-fix`。本仓库只把 Android 作为稳定消息来源和发送
通道，所有业务规则继续由后台管理。

## 1. 职责

Android 侧：

- 检测新通知；
- 打开准确聊天并读取最新入站正文；
- 投递签名幂等事件；
- 在仍然打开的聊天中执行一次文本回复；
- 回传结果。

后台侧：

- 校验账号白名单、HMAC 和事件结构；
- 保存事件并保证同一 `event_id` 只决策一次；
- 使用目标账号 Cookie 创建或复用策略实例；
- 复用现有消息过滤、关键词、默认回复和 AI 决策；
- 返回 `reply`、`noop` 或 `unsupported`；
- 幂等应用发送回执、默认回复一次性记录和聊天历史。

## 2. 去除旧 WebSocket 硬依赖

服务器环境变量：

```dotenv
ANDROID_GATEWAY_ACCOUNT_IDS=CookieID1,CookieID2
```

列入的账号：

- 9090 启动、Cookie 导入或刷新时不启动旧 WebSocket 任务；
- WebSocket 偶尔恢复时不执行这些账号的自动回复发送；
- Android 事件决策不查询旧 WebSocket 最近消息；
- 只要后台有有效 Cookie，就可以临时构建现有策略实例完成决策。

未迁移账号仍可使用旧通道。所有权必须互斥，否则两个通道可能重复回复。

## 3. 服务器配置

在 `xianyu-auto-reply-fix/.env` 中设置：

```dotenv
ANDROID_GATEWAY_SHARED_SECRET=使用密码生成器产生的长随机值
ANDROID_GATEWAY_ACCOUNT_IDS=目标账号在后台中的Cookie ID
```

重新创建 Compose 服务：

```bash
docker compose up -d --force-recreate
```

目标账号必须已在 9090“账号管理”中导入有效 Cookie。后台前端扫码登录只是取得 Cookie 的
方式之一；Android 网关本身不使用二维码登录。

服务器本机健康检查：

```bash
curl http://127.0.0.1:8090/api/android-gateway/v1/health
```

Windows 使用 `config.json.gateway.base_url` 中的地址，例如：

```powershell
Invoke-RestMethod http://服务器Tailscale地址:9090/api/android-gateway/v1/health
```

期望：

```json
{
  "ok": true,
  "enabled": true,
  "service": "android-message-gateway"
}
```

`enabled=false` 说明共享密钥没有进入当前服务进程。

## 4. Android 配置

```json
{
  "gateway": {
    "base_url": "http://服务器Tailscale地址:9090",
    "account_id": "与后台Cookie ID一致",
    "device_id": "android-primary",
    "shared_secret_env": "ANDROID_GATEWAY_SHARED_SECRET",
    "state_file": "var/gateway-state.json",
    "notification_state_file": "var/gateway-notification-state.json",
    "request_timeout_seconds": 30,
    "max_attempts": 3
  }
}
```

手工启动时把共享密钥放入环境变量；常驻模式由 DPAPI 注入：

```powershell
$env:ANDROID_GATEWAY_SHARED_SECRET = "与服务器相同的密钥"
.\.venv\Scripts\xianyu-msg.exe --config config.json gateway --interval 0.5
```

客户端会禁用环境代理，并且只允许 HTTPS、回环 HTTP 或 Tailscale `100.64.0.0/10` HTTP。

## 5. API

### 健康检查

```http
GET /api/android-gateway/v1/health
```

无需签名，不含账号数据。

### 提交事件

```http
POST /api/android-gateway/v1/events
Content-Type: application/json
X-Gateway-Timestamp: <Unix秒>
X-Gateway-Signature: <HMAC-SHA256十六进制>
```

请求：

```json
{
  "event_id": "SHA-256",
  "device_id": "android-primary",
  "account_id": "后台Cookie ID",
  "notification_id": "通知指纹",
  "sender_label": "x***3",
  "body": "消息正文",
  "observed_at": "2026-08-02T15:10:59.845388Z"
}
```

约束：

- ID 字段不能为空且不超过 128 字符；
- `sender_label` 不超过 256 字符；
- `body` 不超过 10,000 字符；
- `observed_at` 必须是有效时间；
- `account_id` 必须在服务器白名单中。

响应：

```json
{
  "event_id": "SHA-256",
  "duplicate": false,
  "decision": {
    "action": "reply",
    "text": "回复内容",
    "source": "关键词",
    "reason": "matched"
  },
  "correlation_status": "notification_only"
}
```

`duplicate=true` 表示同一事件已存在，返回缓存决策，不重复运行业务副作用。

### 提交回执

```http
POST /api/android-gateway/v1/events/{event_id}/receipt
Content-Type: application/json
X-Gateway-Timestamp: <Unix秒>
X-Gateway-Signature: <HMAC-SHA256十六进制>
```

请求：

```json
{"outcome":"sent"}
```

允许的 outcome：

| outcome | 含义 |
|---|---|
| `sent` | Android UI 已确认新增回复气泡 |
| `skipped` | 后台决定不回复 |
| `send_unconfirmed` | 最多点击一次，但无法确认发送结果 |
| `failed` | 决策或执行不受支持 |

响应中的 `changed=false` 表示同一回执已经保存。不同 outcome 重复提交会返回冲突，避免覆盖
已有事实。

## 6. 签名

两个 POST 的签名原文：

```text
timestamp + "\n" + raw_body
```

算法：

```text
HMAC-SHA256(shared_secret, message).hexdigest()
```

服务器使用常量时间比较，并默认只接受与当前时间相差不超过 300 秒的请求。两端系统时钟必须
正确。共享密钥不得放入请求正文、Git 或日志。

## 7. 决策映射

后台复用现有 `decide_chat_message_reply`：

| 后台原始结果 | Android 决策 | 行为 |
|---|---|---|
| 文本回复 | `reply` | 精确输入并单次发送 |
| 无规则/被过滤 | `noop` | 不触碰输入框，回执 `skipped` |
| 图片回复 | `unsupported` | 不把图片标记当文本发送，回执 `failed` |

Android 事件不能稳定提供真实买家 ID、商品 ID 或 WebSocket 会话 ID。后台使用：

```text
chat_id = sender_id = android:<SHA256(account_id + sender_label)前24位>
item_id = ""
```

所以通用关键词、默认回复和 AI 可用；依赖精确商品或真实买家的规则不会命中。

## 8. SQLite 审计

后台数据库默认是 `data/xianyu_data.db`，表 `android_gateway_events` 保存：

| 字段 | 内容 |
|---|---|
| `event_id` | 幂等主键 |
| `event_json` | 原始 Android 事件 |
| `resolution_json` | 关联状态和决策 |
| `receipt_outcome` | 最终回执 |
| `receipt_applied_at` | 业务副作用完成时间 |
| `created_at` | 事件首次保存时间 |
| `decided_at` | 决策保存时间 |
| `completed_at` | 回执保存时间 |

完整成功链路应同时满足：

- `resolution_json.decision.action=reply`；
- `receipt_outcome=sent`；
- `receipt_applied_at` 非空；
- 入站和出站聊天记录按 `event_id` 幂等落库。

## 9. 失败行为

| 阶段 | 行为 |
|---|---|
| 健康检查失败 | 不打开通知，保留以后重试机会 |
| HMAC/账号校验失败 | HTTP 4xx，保留 Android pending 供调查 |
| 后台 5xx/网络失败 | Android 按配置重试 HTTP，不点击发送 |
| 事件重复 | 返回缓存决策 |
| Cookie 缺失 | `noop/account_cookie_not_found` |
| 图片决策 | `unsupported`，不发送文本 |
| 回执重复 | 幂等返回，不重复写聊天记录 |
| 发送边界崩溃 | Android 回报 `send_unconfirmed`，不再次点击 |

## 10. 联调检查表

- 两端共享密钥一致；
- Windows 与服务器时间同步；
- `account_id` 在后台存在有效 Cookie；
- `ANDROID_GATEWAY_ACCOUNT_IDS` 包含该 ID；
- Android 健康检查访问的是正确 9090 地址；
- 旧 WebSocket 不再管理该账号；
- 一条真实消息产生一个事件、一个决策、最多一个回复和一个回执；
- 临时验收规则在完成后删除。
