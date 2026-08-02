# 验收手册与记录

本文件既是发布前验收步骤，也是当前真实设备能力证据。单元测试不能替代通知、Flutter UI、
输入法和实际发送的真机检查。

## 1. 当前已验证环境

| 项目 | 值 |
|---|---|
| 日期 | 2026-08-02 |
| 手机 | 小米 13 |
| 分辨率 | 1080 × 2400 |
| Android | 14 |
| 闲鱼包名 | `com.taobao.idlefish` |
| 闲鱼版本 | 7.19.70，versionCode 419 |
| 聊天 Activity | `com.idlefish.flutterbridge.flutterboost.boost.FishFlutterBoostActivity` |
| 交易聊天频道 | `mipush|com.taobao.idlefish|107787` |
| Windows 常驻方式 | 交互式用户计划任务 |
| 后台 | `xianyu-auto-reply-fix` 9090 Android Gateway API |

设备序列号、账号 Cookie ID、共享密钥和私有截图只保存在 Git 忽略的本地文件中。

## 2. 发布前自动检查

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\xianyu-msg.exe --config config.json doctor
```

当前仓库在最终链路修复后：

- 48 项测试通过；
- `git diff --check` 通过；
- `doctor` 确认 ADB、输入注入、闲鱼包和版本。

测试覆盖：

- 通知 dumpsys 解析、频道过滤、首次基线和去重；
- 通知标题延迟渲染等待；
- 最新入站气泡底部 90% 边界；
- 本地队列租约、确认、重试、死信和文件锁；
- HMAC 请求和安全 URL；
- 事件幂等、发送阶段持久化和崩溃恢复；
- AdbKeyboard 精确输入和原输入法恢复；
- 发送后聊天重开确认；
- Windows 计划任务、DPAPI、ACL、日志轮转和重启重放参数。

## 3. 真机端到端验收步骤

### 3.1 准备

1. 目标闲鱼账号已在手机和 9090 后台正确配置；
2. 后台 Cookie 有效；
3. 创建一个只用于验收的唯一关键词和唯一文本回复；
4. Windows 计划任务处于 `Running`；
5. 手机解锁并回到桌面，闲鱼位于后台；
6. 原系统输入法处于正常启用状态；
7. 不手工打开通知或聊天。

### 3.2 发送

从另一个自有闲鱼账号发送唯一关键词。等待网关自动完成，不在手机上干预。

### 3.3 Android 证据

检查：

```powershell
Get-Content .\var\service\gateway.log -Tail 200
Get-Content .\var\gateway-state.json -Raw | ConvertFrom-Json
Get-Content .\var\gateway-notification-state.json -Raw | ConvertFrom-Json
```

要求：

- 产生一个新 `event_id`；
- `body` 与闲鱼聊天实际显示一致；
- 状态最终为 `sent`；
- `sent_clicks=1`；
- `pending=null`；
- completed 摘要含该事件和回复哈希；
- 通知指纹在成功后才进入确认账本。

### 3.4 后台证据

`android_gateway_events` 对应行要求：

- `event_json.body` 正确；
- `resolution_json.correlation_status=notification_only`；
- `decision.action=reply`；
- `decision.text` 与预期完全一致；
- `decision.source` 符合配置；
- `receipt_outcome=sent`；
- `receipt_applied_at` 非空；
- `created_at`、`decided_at`、`completed_at` 非空且顺序合理。

### 3.5 UI 证据

只读打开对应聊天：

- 入站 marker 恰好一条；
- 精确回复恰好一条；
- 没有截断、大小写变化或重复气泡；
- “未读”只表示对方未读，不影响 `sent`；
- 检查完成后手机回到桌面；
- 当前输入法已经恢复。

### 3.6 收尾

- 删除临时关键词规则；
- 确认计划任务仍在运行；
- 确认 9090 健康接口正常；
- 私有截图只在确有需要时保留；
- 不把 Cookie ID、聊天正文或共享密钥写入公开报告。

## 4. 2026-08-02 最终自动链路记录

第二个自有账号发送：

```text
auto_e2e_fastime_002
```

后台临时关键词决策回复：

```text
ANDROID_FASTIME_REPLY_OK_20260802_2245
```

实际自动结果：

| 证据 | 结果 |
|---|---|
| event ID | `89a55de91853135984fbe1bdc95c991e781336640fe65410771a47acb9b7f95e` |
| notification ID | `99eaa1b9aeda92f2a93aca92e59da1c4b61ac76341f2602b90a40b7788283bd7` |
| 入站正文 | `auto_e2e_fastime_002` |
| 关联状态 | `notification_only` |
| 决策 | `reply` |
| 决策来源 | `关键词` |
| Android 结果 | `sent` |
| 回执 | `sent` |
| `receipt_applied_at` | `2026-08-02T15:11:15.338394+00:00` |
| UI 入站计数 | 1 |
| UI 精确回复计数 | 1 |
| 重复发送 | 0 |

该验收全程由活动通知自动触发，没有人工代发。后台事件、决策、Android UI 发送确认和服务器
回执一致。临时关键词规则随后精确删除。

## 5. 本轮发现并修复的问题

### AdbKeyboard 安装与精确文本

早期使用系统输入法时，ASCII 回复可能停留在候选区或被截断。修复为：

- 首次有人值守安装 AdbKeyboard；
- 网关无人值守时若未安装则失败，不弹出安装；
- 发送时临时切换并精确提交；
- 输入完成后恢复原输入法。

### 最新气泡过滤

靠近输入栏的新消息底部超过旧 85% 阈值，导致解析到上一条消息。边界更新为屏幕高度 90%，
并增加回归测试。

### Flutter 可访问性树陈旧

实际发送成功后，当前聊天层级短时间仍没有新回复。修复为等待超时后退出并按唯一标题重开
聊天，再比较回复数量。

### 通知栏标题延迟渲染

通知栏刚展开时标题选择器可能返回 0，约 0.5 秒后才出现。修复为在页面等待窗口内轮询，
而不是第一次查询失败就放弃。

### 监督器重启漏掉现有未处理通知

每次重启都按首次基线处理会把失败前仍存在的通知标记为已见。修复为：

- 真正首次启动且状态文件不存在时建立安全基线；
- 状态文件存在后的监督器重启添加 `--include-existing`；
- 已确认通知仍由指纹账本去重。

最终 `auto_e2e_fastime_002` 验收同时覆盖了以上修复。

## 6. 历史里程碑

### 手工单会话发送

早期 `AUTO_E2E_001` 验证了：marker 唯一、dry-run、单次点击、发送后气泡确认和重复保护。

### 真实通知路由

`AUTO_e2e_002` 验证了：交易聊天频道通知、遮罩标题唯一点击、聊天 Activity、正文读取和零发送
的只读路由。

### 本地待处理队列

`AUTO_e2e_003` 验证了：通知自动打开、最新左侧气泡入队、重复抑制、返回桌面以及
claim/fail 真实 CLI 状态转换。

### 后台网关初次联调

后续测试完成了 Android 事件到 9090 关键词决策和真实回复，并逐步暴露输入法、气泡刷新、
通知渲染和重启基线问题。最终记录取代这些中间结果作为当前通过标准。

## 7. 当前证明与未证明

已经证明：

- 指定设备和闲鱼版本上的通知到达与准确开聊；
- 最新可见文本消息读取；
- 不依赖旧 WebSocket 的后台决策；
- AdbKeyboard 完整文本输入；
- 最多一次发送点击；
- UI `sent` 确认和服务器回执；
- 进程重启对未确认活动通知的恢复；
- 单实例 Windows 常驻运行。

尚未证明或不支持：

- 所有手机型号和未来闲鱼版本；
- 锁屏状态下的可靠 UI 操作；
- 闲鱼前台不产生通知时的消息发现；
- 超出可见屏幕的多条聚合消息完整补齐；
- 相同遮罩发送者标题的歧义会话；
- 图片自动回复；
- 依赖真实商品 ID 或买家 ID 的规则；
- 多手机、多账号并行的分布式调度。

任何涉及这些边界的扩展都必须新增测试夹具并重新执行真机 E2E，不能沿用本记录推断通过。
