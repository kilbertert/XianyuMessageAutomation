# 设备准备与坐标校准

示例配置在小米 13、1080 × 2400、Android 14、闲鱼 7.19.70 上验证。更换设备、系统、
分辨率、字体、输入法或闲鱼版本后必须重新校准。

## 1. Android 设置

在开发者选项中开启：

- USB 调试；
- USB 调试（安全设置）。

然后：

1. 使用可靠数据线连接；
2. 解锁手机；
3. 接受 Windows 电脑的 RSA 调试授权；
4. 确认闲鱼已登录目标自有账号；
5. 开启闲鱼通知和“交易聊天消息”频道；
6. 确保系统不会立即冻结闲鱼后台通知；
7. 运行时让手机回到桌面，闲鱼留在后台。

检查：

```powershell
adb devices
.\.venv\Scripts\xianyu-msg.exe --config config.json doctor
```

`doctor` 只证明 ADB、输入注入和包信息正常，不证明坐标仍准确。

## 2. 有人值守安装 AdbKeyboard

生产网关不会自动安装 APK。第一次必须在手机解锁状态下触发安装，并人工同意：

```powershell
.\.venv\Scripts\python.exe -c "import uiautomator2 as u2; u2.connect('设备序列号').set_input_ime(True)"
```

如果误点拒绝，重新执行同一命令即可再次触发安装。安装成功后确认：

```powershell
adb -s 设备序列号 shell ime list -s
```

必须包含：

```text
com.github.uiautomator/.AdbKeyboard
```

查看当前输入法：

```powershell
adb -s 设备序列号 shell dumpsys input_method | Select-String mCurMethodId
```

恢复日常输入法：

```powershell
adb -s 设备序列号 shell ime set 你的输入法ID
```

正式回复时程序自动保存当前 IME、临时切换 AdbKeyboard、精确写入文本，再恢复原 IME。

## 3. 坐标含义

| 字段 | 含义 | 使用路径 |
|---|---|---|
| `message_tab` | 闲鱼底部消息 Tab 中心 | `unread`、`screenshot-list`、手工 `reply` |
| `conversation_x` | 与命令行会话 Y 组合的横向位置 | 手工 `reply --conversation-y` |
| `input` | 聊天底部输入框中心 | `reply`、`gateway` |
| `candidate_commit` | 旧输入法候选提交点，当前仅保留配置兼容 | 当前网关不使用 |
| `send` | 无键盘状态下黄色发送按钮中心 | `reply`、`gateway` |

配置点使用屏幕比例：

```text
x_ratio = x_pixel / display_width
y_ratio = y_pixel / display_height
```

只有 `reply --conversation-y` 是直接传入像素 Y。

## 4. 获取屏幕尺寸

```powershell
adb -s 设备序列号 shell wm size
```

确认实际显示尺寸与预期一致。分辨率模式或显示缩放变化都会影响坐标。

## 5. 校准消息 Tab 和会话行

```powershell
.\.venv\Scripts\xianyu-msg.exe --config config.json screenshot-list `
  --output var\message-list.png
```

在截图中确认：

- 消息 Tab 被正确打开；
- 目标会话位于可见区域；
- 记录目标会话行中心的像素 Y；
- 不保留含真实聊天信息的截图，除非确有审计需要。

使用记录的 Y 做 dry-run：

```powershell
.\.venv\Scripts\xianyu-msg.exe --config config.json reply `
  --marker UNIQUE_TEST_MARKER `
  --reply "UNIQUE_TEST_REPLY" `
  --conversation-y 目标会话中心Y
```

只有返回以下结果才说明目标唯一且未发送：

```json
{
  "status": "dry_run_ready",
  "marker_count": 1,
  "reply_count": 0,
  "sent_clicks": 0
}
```

## 6. 校准输入和发送

使用专门测试会话，并保证测试回复唯一。先确认 AdbKeyboard 和原输入法恢复正常，再执行一次
显式发送：

```powershell
.\.venv\Scripts\xianyu-msg.exe --config config.json reply `
  --marker UNIQUE_TEST_MARKER `
  --reply "UNIQUE_TEST_REPLY" `
  --conversation-y 目标会话中心Y `
  --apply `
  --keep-artifacts
```

通过标准：

- 输入框获得完整、区分大小写一致的文本；
- 发送按钮只点击一次；
- 聊天出现一条精确回复气泡；
- `sent_clicks=1`；
- 命令结果为 `sent`；
- 原输入法恢复。

`--keep-artifacts` 会在 `var/artifacts/` 留下私有草稿截图，验证后按隐私要求清理。

## 7. 生产网关校准

手工 `reply` 通过后，还要验证生产主链路，因为 Gateway 额外涉及：

- 通知栏标题渲染和唯一匹配；
- 最新左侧气泡提取；
- 9090 决策；
- 点击前 `sending` 持久化；
- 发送后气泡数量比较；
- Flutter 树陈旧时退出并重开聊天确认；
- 回执落库；
- 返回桌面。

按[验收手册](validation.md)完成一条真实消息，才能恢复无人值守任务。

## 8. 重新校准触发条件

- 闲鱼 App 升级；
- Android 系统更新；
- 更换手机；
- 改变分辨率、DPI、字体大小或显示缩放；
- 更换系统导航方式；
- 输入法被卸载、禁用或布局变化；
- 页面 Activity、按钮或聊天气泡结构变化；
- 日志出现 `target_missing`、`send_unconfirmed` 或焦点验证失败；
- 回复被截断或位置点击错误。

## 9. 安全规则

- 永远先 dry-run；
- 永远使用唯一测试 marker 和唯一回复；
- 不通过连续点击发送来“寻找坐标”；
- `send_unconfirmed` 后先人工检查，不再自动重试；
- 坐标变化后不要直接恢复常驻服务；
- 校准截图和 UI XML 可能含个人信息，保存在 `var/` 并限制访问。
