# 入站检测与本地队列

生产自动回复使用 `gateway`。本文件介绍两个辅助模式：

- `monitor`：只读通知事件流；
- `inbox + queue`：把消息正文写入本地文件队列供其他本地进程消费。

它们适合诊断或独立集成，不要与生产 `gateway` 同时监听同一设备的同一通知账本。

## 1. 通知来源

项目通过 ADB 轮询 Android 通知服务，只解析包名：

```text
com.taobao.idlefish
```

已验证闲鱼 7.19.70 的交易聊天频道：

```text
mipush|com.taobao.idlefish|107787
```

频道完整 ID 配置在 `notifications.message_channel_ids`。默认过滤物流、营销等非聊天通知。

闲鱼通知通常只提供遮罩发送者标题和“发来一条新消息”，不提供真实正文。因此：

- `monitor` 可以证明通知到达，但正文可能是通用文字；
- `inbox` 和 `gateway` 必须点击通知进入准确聊天，才能读取最新气泡；
- 点击通知会把会话标记为已读；
- 闲鱼位于前台时可能不产生系统通知。

## 2. monitor：只读通知

持续运行：

```powershell
.\.venv\Scripts\xianyu-msg.exe --config config.json monitor --interval 0.5
```

限时运行：

```powershell
.\.venv\Scripts\xianyu-msg.exe --config config.json monitor `
  --duration 60 `
  --interval 0.5
```

读取一次并包含当前活动通知：

```powershell
.\.venv\Scripts\xianyu-msg.exe --config config.json monitor `
  --once `
  --include-existing
```

诊断所有闲鱼频道：

```powershell
.\.venv\Scripts\xianyu-msg.exe --config config.json monitor `
  --once `
  --include-existing `
  --all-notifications
```

`monitor` 不打开聊天、不输入文字、不点击发送。

### 输出

每个事件输出一行 JSON，包含：

- `fingerprint` 和 `source_key_sha256`；
- 包名、频道、类别、Android 更新时间；
- 本地观察时间；
- 标题、文本和展开文本；
- `message_candidate`。

同时追加到 `var/inbound-notifications.jsonl`。状态文件只保存哈希，但 JSONL 可能含发送者标题
和通知文字。

## 3. 首次基线

默认第一次快照把现有通知记为基线，不输出它们。这样启动监控不会把旧通知误认为新消息。

`--include-existing` 只适合受控诊断或明确的恢复流程。生产监督器会在通知状态已初始化后自动
使用它，保证重启时尚未确认的活动通知不丢失。

## 4. inbox：打开聊天并入队

```powershell
.\.venv\Scripts\xianyu-msg.exe --config config.json inbox --interval 0.5
```

每条新通知的流程：

1. 标题必须精确匹配一个通知；
2. 点击后必须进入闲鱼聊天 Activity；
3. 从屏幕高度 20% 到 90% 的消息区域解析文本节点；
4. 按横向位置只保留左侧入站气泡；
5. 取最新可见正文；
6. 追加一个幂等记录到 `var/inbound-pending.jsonl`；
7. 成功入队后才确认通知；
8. 按 Home，并确认闲鱼不再是前台。

`inbox` 绝不触碰输入框或发送按钮。打开聊天仍会导致闲鱼将会话标记为已读。

### 队列记录

记录包含：

- 消息指纹；
- 通知指纹；
- 遮罩发送者标题；
- 正文；
- 通知观察时间；
- 入队时间。

`var/inbound-pending.jsonl` 含正文，必须作为私有数据。入队去重状态只保存哈希。

## 5. queue：租约消费

领取最早可用消息：

```powershell
.\.venv\Scripts\xianyu-msg.exe --config config.json queue claim `
  --worker-id reply-policy-1 `
  --lease-seconds 300
```

成功处理后，由同一个 worker 确认：

```powershell
.\.venv\Scripts\xianyu-msg.exe --config config.json queue ack `
  --worker-id reply-policy-1 `
  --fingerprint MESSAGE_SHA256
```

处理失败时释放重试：

```powershell
.\.venv\Scripts\xianyu-msg.exe --config config.json queue fail `
  --worker-id reply-policy-1 `
  --fingerprint MESSAGE_SHA256 `
  --reason "downstream unavailable" `
  --max-attempts 3
```

语义：

- 只有租约所有者可以 ack/fail；
- 租约过期后消息会再次投递，attempt 增加；
- 失败低于上限时回到 pending；
- 达到上限后进入 dead，不再自动领取；
- 状态转换使用本地 OS 文件锁；
- 失败原因只保存哈希；
- 消费者必须幂等，因为这是至少一次交付。

## 6. 为什么生产回复不用本地队列

离开聊天后，当前闲鱼 UI 没有稳定的真实会话 ID 可供稍后重新打开准确聊天。如果把业务
决策异步延迟到本地队列消费之后，发送阶段可能无法证明目标会话。

生产 `gateway` 因此在通知已经打开准确聊天时同步请求 9090 决策，并保持该聊天直到发送或
无需回复结算。文件队列继续保留给只收消息的集成。

## 7. 限制

- ADB 必须持续连接；
- 通知权限和聊天频道必须开启；
- 两次轮询之间发布又移除的通知可能错过；
- 闲鱼可能把多条消息聚合成一个通知更新；
- 当前每个通知只提取最新可见左侧气泡；
- 超出当前屏幕的中间突发消息可能遗漏；
- 遮罩标题相同导致歧义时失败关闭；
- 当前不是跨主机分布式消息队列。

若要完全摆脱 ADB 通知轮询，需要开发并由用户授权一个 Android
`NotificationListenerService` 辅助应用。当前仓库尚未实现该组件。
