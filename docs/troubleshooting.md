# 故障排查

先确认你操作的是本仓库和正确设备。所有示例均在仓库根目录运行。

## 快速诊断

```powershell
adb devices
.\.venv\Scripts\xianyu-msg.exe --config config.json doctor
Get-ScheduledTask -TaskName XianyuAndroidMessageGateway | Format-List TaskName,State
Get-ScheduledTaskInfo -TaskName XianyuAndroidMessageGateway
Get-Content .\var\service\gateway.log -Tail 100
$config = Get-Content .\config.json -Raw | ConvertFrom-Json
Invoke-RestMethod "$($config.gateway.base_url)/api/android-gateway/v1/health"
```

不要一开始就删除状态文件、清除闲鱼数据或重新点击发送。这些动作会丢失恢复依据，甚至导致
重复回复。

## ADB 看不到手机或状态不是 device

现象：

- `adb devices` 没有目标序列号；
- 状态为 `unauthorized` 或 `offline`；
- `doctor` 返回 `device is not connected in adb device state`。

处理：

1. 解锁手机并重新插拔 USB；
2. 检查 USB 模式和线材；
3. 在手机开发者选项中确认 USB 调试；
4. 对 `unauthorized`，在手机上接受当前电脑 RSA 授权；
5. 执行 `adb kill-server`、`adb start-server` 后复查；
6. 确认 `config.json.serial` 与 `adb devices` 完全一致；
7. 恢复后重新运行 `doctor`。

## 输入法 APK 安装弹窗被拒绝

现象：首次输入时弹出安装 APK，但超时或误点拒绝；日志提示：

```text
AdbKeyboard is not installed; complete the attended device setup
```

处理：

```powershell
.\.venv\Scripts\python.exe -c "import uiautomator2 as u2; u2.connect('设备序列号').set_input_ime(True)"
```

保持手机解锁，在手机上同意安装。然后确认：

```powershell
adb -s 设备序列号 shell ime list -s
```

常驻网关不会在无人值守运行时自动安装 APK，这是有意的安全限制。

## 回复被截断、停在候选区或内容不完全一致

原因通常是 AdbKeyboard 未安装、未成功切换，或运行了旧版本代码。

检查：

```powershell
adb -s 设备序列号 shell ime list -s
git log -5 --oneline
```

确认代码包含 AdbKeyboard 精确输入实现，并重新安装可编辑包：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

不要通过连续点击中文候选词或重复发送来补救。先在一条明确测试消息上重新验收。

## 发送后没有新气泡或出现 send_unconfirmed

`send_unconfirmed` 表示系统最多已经点击一次发送，但当前和刷新后的 UI 树都没有确认到新增
精确回复气泡。

立即操作：

1. 不要重启后再次人工点击发送；
2. 人工只读打开目标聊天；
3. 搜索精确回复文本，确认它是否已经出现；
4. 记录 `event_id`、日志、`gateway-state.json` 和后台事件行；
5. 若气泡存在，把事件视为“已发送但自动确认失败”；
6. 若气泡不存在，先调查输入框、坐标、网络和闲鱼 UI 变化，再由人工决定是否补发。

设计上不会自动把 `send_unconfirmed` 重试为第二次点击，因为重复回复的损害高于漏发后的人工
处理成本。

## 收不到任何闲鱼通知

先确保：

- 手机停留在桌面，闲鱼位于后台；
- 闲鱼 App 通知总开关开启；
- “交易聊天消息”频道开启；
- 系统没有冻结闲鱼后台通知；
- 发送方确实给当前手机登录账号发了新消息。

诊断所有闲鱼通知频道：

```powershell
.\.venv\Scripts\xianyu-msg.exe --config config.json monitor `
  --once --include-existing --all-notifications
```

如果新版本使用了不同频道，确认频道含义后更新
`notifications.message_channel_ids`。闲鱼在前台时可能直接刷新聊天而不产生系统通知，这种情况
不是通知网关可恢复的事件来源。

## 通知存在但网关没有处理

检查：

```powershell
Get-Content .\var\gateway-notification-state.json -Raw
Get-Content .\var\service\gateway.log -Tail 100
```

常见原因：

- 该通知已经在账本中确认；
- 通知频道不在白名单；
- 标题为空或同名标题不唯一；
- 任务第一次启动，将已有通知作为了基线；
- 手机通知栏渲染较慢，旧版本在标题出现前查询；
- 服务重启时没有使用 `--include-existing`。

当前监督器在通知状态文件存在时自动添加 `--include-existing`，并轮询等待标题渲染。不要直接
编辑账本，除非已经停止全部网关进程、能确定精确通知指纹且理解重复处理风险。

## notification title is not unique

通知栏或消息列表中相同遮罩标题出现多次，程序无法证明哪个会话正确，因此失败关闭。

处理：

- 人工清理无关旧通知后重试新消息；
- 不要把标题匹配改成“取第一个”；
- 如果平台长期产生重复遮罩标题，需要新增更强的会话标识方案，而不是放宽安全条件。

## no incoming chat message was exposed

网关打开了聊天，但可访问性树没有找到有效左侧气泡。可能原因：

- 通知打开到非聊天页；
- 新消息仍未渲染；
- 闲鱼版本改变了气泡语义或布局；
- 最新消息超出当前可见区域；
- 页面有弹窗遮挡。

使用 uiautomator2 层级和受控截图诊断，不要盲改入站左右阈值。当前解析区域排除屏幕顶部 20%
和底部 10%，并按气泡横向位置区分入站消息。

## 后台健康接口失败

现象：`gateway health check failed`、连接超时或 `enabled=false`。

处理顺序：

1. Windows 能否访问服务器 Tailscale IP；
2. 9090 端口是否监听；
3. 服务器容器是否运行；
4. `.env` 是否设置 `ANDROID_GATEWAY_SHARED_SECRET`；
5. 修改 `.env` 后是否执行 `docker compose up -d --force-recreate`；
6. `config.json.gateway.base_url` 是否正确；
7. 系统时钟是否正确。

客户端会绕过环境 HTTP 代理访问 Tailscale。普通公网 HTTP 会被安全校验拒绝，应改用 HTTPS
或 Tailscale 地址。

## 401 invalid gateway signature

原因：

- Windows 与服务器共享密钥不同；
- 服务器容器仍在使用旧环境变量；
- 两端系统时间相差超过五分钟；
- 请求正文在签名后被中间层修改。

重新设置服务器环境和 Windows DPAPI 密钥，并校准两端时钟。不要把真实密钥输出到日志进行
比对。

## account_not_configured 或 account_cookie_not_found

检查三个值是否指向同一个账号：

- `config.json.gateway.account_id`；
- 服务器 `ANDROID_GATEWAY_ACCOUNT_IDS`；
- 9090 账号管理中的 Cookie ID。

账号必须已经导入有效 Cookie。Android 网关不要求旧 WebSocket 实例运行，但后台需要 Cookie
来构造现有业务决策实例。

## 后台没有命中商品或买家专属规则

先检查事件的 `correlation_status` 和 `decision.reason`。网关只信任 Activity Intent 中同时
出现的显式会话 ID 与买家 ID；否则后台只用五分钟内、正文一致且唯一的本地真实聊天记录。
没有唯一身份时返回 `identity_not_correlated` 或 `identity_ambiguous` 并跳过回复。

系统不再从遮罩昵称合成 `android:<hash>` 身份。真实 `item_id` 未提供时，依赖商品 ID 的规则
不会命中；这是失败关闭，不应通过降低关联条件绕过。

## 同一消息出现两条回复

立即停止 Android 计划任务并检查：

- 是否手工运行了第二个 `gateway`；
- 是否有多个 `gateway_service.ps1` 根进程；
- 服务器 `ANDROID_GATEWAY_ACCOUNT_IDS` 是否包含该账号；
- 旧 WebSocket 自动回复是否仍在管理该账号；
- 两条回复是否来自不同规则或人工操作。

Android 本地账本只能约束本实例的发送，无法阻止另一个进程或旧通道发送。修复并发所有权后
再恢复任务。

## 任务显示 Running，但 LastTaskResult 是 267009

这是 Windows 计划任务的 `0x41301`，含义是“任务当前正在运行”。只要 `State=Running` 且
日志持续正常，它不是错误。

真正的失败应结合任务状态、日志和进程检查，而不是只看十进制结果值。

## 任务反复重启

查看：

```powershell
Get-Content .\var\service\gateway.log -Tail 200
```

监督器在 CLI 退出后等待 10 秒再启动。反复出现 `gateway_stopped` 或
`gateway_exception` 通常表示配置、密钥文件、ADB、后台健康或状态恢复失败。

先修复首个重复异常，不要通过降低重启间隔掩盖原因。

## 输入法没有恢复

检查当前和可用输入法：

```powershell
adb -s 设备序列号 shell dumpsys input_method | Select-String mCurMethodId
adb -s 设备序列号 shell ime list -s
```

手工恢复：

```powershell
adb -s 设备序列号 shell ime set 你的原输入法ID
```

当前实现会在 `finally` 中恢复发送前输入法，并验证恢复结果。若持续失败，先停止常驻任务，
检查系统是否禁用了原输入法。

## 手机没有回到桌面

成功处理后程序会按 Home，并通过 `dumpsys window` 验证闲鱼不再是前台。失败时聊天页会被
有意保留，方便恢复或人工检查。

因此先看是否存在未完成 `pending` 或异常；不要在失败后立即强制 Home 并清理状态。

## 收集诊断信息

可以收集：

```powershell
.\.venv\Scripts\xianyu-msg.exe --config config.json doctor
Get-ScheduledTaskInfo -TaskName XianyuAndroidMessageGateway
Get-Content .\var\service\gateway.log -Tail 200
git status --short --branch
git log -5 --oneline
```

分享前必须删除或遮盖：

- 聊天正文和发送者标签；
- Cookie ID；
- 共享密钥和签名；
- 私有 Tailscale 地址；
- 截图中的头像、商品和聊天内容。
