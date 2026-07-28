# Validation record

## Environment

- Date: 2026-07-28
- Device: Xiaomi 13, 1080 × 2400
- Android: 14
- ADB serial: kept only in ignored `config.json`
- Xianyu package: `com.taobao.idlefish`
- Xianyu version: 7.19.70 (`versionCode` 419)

## True end-to-end send

The inbound marker `AUTO_E2E_001` was sent from a second owned account.

- unread count changed from 6 to 7;
- the marker appeared exactly once in the chat hierarchy;
- the exact reply `收到，这是自动化联调测试。` was committed through the system IME;
- the Xianyu Send control was clicked exactly once;
- one matching outgoing bubble and one `已读` indicator were observed;
- unread count returned from 7 to 6.

## Repository regression

The repository implementation was then run against the same conversation with `--apply`.
The duplicate guard returned:

```json
{
  "status": "skipped_duplicate",
  "marker_count": 1,
  "reply_count": 1,
  "sent_clicks": 0,
  "unread_before": 6
}
```

After adding chat-to-list navigation handling:

- 11 automated tests passed;
- `doctor` confirmed ADB, input injection, package, and version;
- `unread` returned 6 from both the list and a prior chat state;
- a second duplicate regression again produced zero Send clicks.

Private verification screenshots were deleted after inspection.

## What this proves

This validates the controlled single-conversation path, the Chinese IME flow, post-send
confirmation, and duplicate protection on this device/app combination. It does not yet prove
unattended routing across every conversation; the custom-drawn conversation list still needs
notification-based routing or OCR before that milestone can be claimed.
