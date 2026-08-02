# 详细架构

根目录 [DESIGN.md](../DESIGN.md) 说明系统级方案，本文件聚焦本仓库的模块、数据流和失败
恢复实现。

## 1. 分层

```text
CLI 层
  cli.py                         参数、组合依赖、JSON 输出和退出码

工作流层
  GatewayWorkflow               生产 event → decision → send → receipt
  InboundWorkflow/InboundPoller  只收消息并写本地队列
  ReplyWorkflow                 指定会话 dry-run / 单次发送
  QueueConsumer                 本地队列租约消费

适配层
  Uiautomator2Device             闲鱼启动、通知点击、UI 树、输入和坐标点击
  AdbNotificationSource         dumpsys notification 解析
  GatewayClient                 Tailscale/HMAC HTTP 客户端

状态层
  GatewayDeliveryStore          生产发送恢复账本
  NotificationStateStore        通知基线与去重
  InboundQueue                  追加式消息队列
  QueueConsumer state           租约、重试、完成和死信
  StateStore                    手工 reply 去重
```

工作流依赖 Protocol 接口而不是直接依赖真机实现，测试因此可以使用内存假设备验证“最多一次
点击”等关键不变量。

## 2. 模块职责

| 模块 | 核心对象 | 职责 |
|---|---|---|
| `config.py` | `AutomationConfig` | 读取和验证 JSON 配置、解析相对路径 |
| `doctor.py` | `AdbDoctor` | 检查 ADB、设备状态、输入注入、闲鱼包和版本 |
| `notifications.py` | `AdbNotificationSource` | 执行通知 dumpsys、解析闲鱼通知和频道 |
| `monitor.py` | `NotificationMonitor`、`NotificationStateStore` | 基线、通知去重、JSONL 输出 |
| `device.py` | `Uiautomator2Device` | 页面导航、唯一通知点击、聊天验证、精确输入、单次发送 |
| `parser.py` | `find_text`、`unread_count` | 解析可访问性 XML 文本、边界和未读数 |
| `inbound.py` | `InboundWorkflow`、`InboundQueue` | 提取最新左侧正文并写入本地队列 |
| `consumer.py` | `QueueConsumer` | 以文件锁实现租约、确认、失败重试和死信 |
| `gateway.py` | `GatewayClient`、`GatewayWorkflow`、`GatewayDeliveryStore` | 生产主链路、HMAC、幂等恢复和回执 |
| `workflow.py` | `ReplyWorkflow` | 手工标记唯一性、dry-run 和重复保护 |
| `store.py` | `StateStore` | `reply` 模式原子哈希账本 |
| `models.py` | 各 dataclass/StrEnum | 工作流输入、结果和状态 |

## 3. CLI 组合

`cli.py` 是唯一公开入口，安装后生成 `xianyu-msg.exe`。

| 命令 | 组合对象 | 退出码 0 的主要状态 |
|---|---|---|
| `doctor` | `AdbDoctor` | `ok=true` |
| `unread` | `Uiautomator2Device` + parser | 正常读到页面 |
| `screenshot-list` | `Uiautomator2Device` | 截图写入成功 |
| `monitor` | notification source + monitor + sink | 轮询正常结束 |
| `inbox` | source + notification state + inbound workflow | 轮询正常结束 |
| `gateway` | source + delivery store + gateway workflow | 正常运行；单次恢复按结果决定 |
| `queue` | `QueueConsumer` | 状态转换成功 |
| `reply` | `ReplyWorkflow` | `dry_run_ready`、`sent` 或 `skipped_duplicate` |

所有正常输出为 UTF-8 JSON。可恢复的业务结果也可能使用退出码 2，例如
`send_unconfirmed`；调用方必须同时检查 JSON 状态，不能只看 stdout 文本。

## 4. 通知检测

### 4.1 来源

`AdbNotificationSource` 执行：

```text
adb -s <serial> shell dumpsys notification --noredact
```

解析只保留闲鱼包 `com.taobao.idlefish`。`message_candidate` 依据配置频道白名单或标准消息
元数据判断。生产应配置完整交易聊天频道 ID，避免把物流或营销通知当成聊天。

### 4.2 指纹和基线

每个通知事件包含源键哈希、内容和更新时间形成的指纹。状态文件只保存指纹和时间，不保存
源键原文。

默认首次快照只建基线：

```text
snapshot -> record all -> emit none
```

使用 `include_existing` 时：

```text
snapshot -> calculate unseen -> process -> acknowledge successful items
```

`InboundPoller` 只在工作流成功后确认通知，因此路由失败仍可重试。常驻监督器根据网关通知
状态文件是否存在决定是否添加 `--include-existing`，解决进程重启期间仍在通知栏的未处理
事件。

## 5. 聊天路由和正文提取

1. 后台健康检查必须先通过；
2. 展开通知栏；
3. 在等待窗口内轮询通知标题，兼容通知栏渐进渲染；
4. 标题文本或 description 必须精确匹配一次；
5. 点击后必须进入配置的聊天 Activity；
6. 解析可访问性树中的文本节点；
7. 只保留屏幕高度 20% 到 90% 区域内、横向位于左侧的消息气泡；
8. 取最后一条可见入站消息作为正文。

标题不唯一、Activity 不正确或没有入站气泡都会失败关闭，不猜测目标。

## 6. 生产 GatewayWorkflow

### 6.1 新事件

```text
notification
  -> health
  -> open_notification
  -> extract latest inbound
  -> begin(extracted)
  -> submit event
  -> set_decision(decided)
  -> execute decision
  -> receipt
  -> complete
  -> Home
```

事件字段：

| 字段 | 来源 |
|---|---|
| `event_id` | 通知指纹与正文的 SHA-256 |
| `device_id` | `config.json` |
| `account_id` | 后台 Cookie ID 配置 |
| `notification_id` | 通知指纹 |
| `sender_label` | 通知标题，通常是遮罩昵称 |
| `body` | 最新可见左侧气泡 |
| `observed_at` | 本地观察通知的 UTC 时间 |

### 6.2 决策

- `reply`：验证当前聊天仍以同一入站正文结尾，然后准备发送；
- `noop`：产生 `skipped` 回执，不触碰输入框；
- `unsupported`：产生 `failed` 回执，当前用于图片回复；
- 其他 action：协议错误，保留 pending 供调查。

### 6.3 精确输入

`prepare_reply`：

1. 确认 AdbKeyboard 已安装，拒绝无人值守安装；
2. 点击输入框；
3. 保存当前 IME；
4. 临时启用 AdbKeyboard；
5. 清空并补充删除键；
6. 使用 `send_keys` 提交精确文本；
7. 在 `finally` 中恢复原 IME，并验证恢复成功。

`send_once` 只有在 `_reply_prepared=true` 时才允许执行，执行后立即清除该标志并增加
`sent_clicks`。

### 6.4 发送确认

发送前记录页面中精确回复文本的数量。点击后轮询，只有数量增加才确认成功。Flutter 树可能
在气泡已经发送后保持陈旧，因此超时后会：

1. 退出当前聊天；
2. 在消息列表中按唯一遮罩标题重新进入；
3. 读取新的层级；
4. 再次比较精确文本数量。

仍未增加则返回 `send_unconfirmed`，不二次点击。

## 7. 崩溃恢复

`GatewayDeliveryStore` 的 pending 阶段：

| 阶段 | 恢复行为 |
|---|---|
| `extracted` | 重投幂等事件，获取或复用后台决策 |
| `decided` | 验证当前聊天后继续单次发送 |
| `sending` | 不再点击，直接按 `send_unconfirmed` 结算 |
| `sent` | 补发 `sent` 回执并完成本地账本 |
| `send_unconfirmed` | 补发同名回执，不再点击 |

CLI 启动时如果发现 pending，会在轮询新通知前调用 `resume()`。恢复要求目标聊天仍处于前台；
失败时聊天被保留，方便人工或监督器下一次恢复。

HTTP 的 `max_attempts` 只重试事件和回执请求，不重试 UI 发送点击。

## 8. 本地 inbox/queue 路径

该路径用于只收消息或其他本地集成，不参与生产同步回复。

```text
notification -> exact chat -> latest inbound -> append JSONL -> Home
                                              |
                                              v
                             claim -> processing -> ack/done
                                      |       |
                                      |       +-> fail at limit -> dead
                                      +-> lease expires -> later claim
```

语义：

- `inbound-pending.jsonl` 是追加日志，含完整消息；
- 入队状态以消息指纹去重；
- `QueueConsumer` 用 Windows 文件锁保护状态转换；
- claim 是至少一次交付，消费者必须幂等；
- 只有租约所有者可以 ack/fail；
- 失败原因只保存 SHA-256，不保存明文；
- 达到 `max_attempts` 后进入死信。

该文件队列适合当前单机部署，不是跨主机分布式消息中间件。

## 9. 手工 reply 路径

`ReplyWorkflow` 用于校准或受控单会话验证：

- 目标可以是可见消息列表中的 Y 坐标，或已经打开的当前聊天；
- marker 必须恰好出现一次；
- 页面已存在精确回复或哈希账本已完成时跳过；
- 默认 dry-run；
- 只有显式 `--apply` 才输入和点击；
- 当前旧工作流直接等待当前树，不使用 Gateway 的重开确认，因此生产验收应以 `gateway`
  主路径为准。

## 10. 状态与原子性

JSON 状态文件采用：

1. 同目录创建临时文件；
2. 完整写入 JSON；
3. `os.replace` 原子替换。

本地队列的多进程状态转换额外使用 OS 文件锁。生产 Gateway 当前限定一个进程和一个
飞行中事件，不提供多实例分布式锁；运维层必须保证单实例。

## 11. 安全不变量

- 所有 UI 路由在目标不唯一时失败关闭；
- 监控模式绝不打开聊天或发送；
- `inbox` 绝不输入文本或点击发送；
- `reply` 默认 dry-run；
- Gateway 点击前持久化 `sending`；
- 普通公网 HTTP 被拒绝；
- HMAC 密钥只从环境读取；
- 服务密钥由 Windows DPAPI 保护；
- 日志、状态、队列和截图均位于 Git 忽略目录；
- 处理结束回到 Home 并确认闲鱼不在前台。

## 12. 已知边界

- ADB 轮询可能错过在两个快照之间发布又移除的通知；
- 闲鱼聚合多个消息时只保证最新可见气泡；
- 遮罩标题相同会导致歧义；
- 手机锁屏、系统弹窗或闲鱼前台状态会影响路由；
- UI 坐标和 Activity 可能随版本改变；
- 图片发送尚未实现；
- 脱敏会话无法支持精确商品/买家规则；
- 当前没有独立 Android `NotificationListenerService`，仍依赖 ADB 常连。

## 13. 测试边界

单元测试覆盖纯解析、状态机、HTTP 签名、恢复和模拟设备行为。以下能力必须使用真机回归：

- 通知频道与标题；
- Flutter Activity 和可访问性树；
- 输入框、AdbKeyboard 和原输入法恢复；
- 发送按钮坐标；
- 发送后气泡确认；
- Windows 计划任务、ADB 和 9090 的完整链路。

具体步骤和当前证据见[验收手册与记录](validation.md)。
