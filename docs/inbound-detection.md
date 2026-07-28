# Inbound detection

## Current path

The `monitor` command polls Android's notification service through ADB and parses only records
whose package is `com.taobao.idlefish`. On the validated device, Xianyu 7.19.70 uses the channel
ending in `107787` for `交易聊天消息`; that full channel ID is configured as an explicit message
candidate allowlist.

Every unseen notification snapshot produces one JSON object on stdout and one line in
`var/inbound-notifications.jsonl`. A notification update is treated as a new event when its
Android update timestamp or content changes.

```powershell
.\.venv\Scripts\xianyu-msg.exe --config config.json monitor --interval 0.5
```

The first snapshot is a baseline by default, so notifications that existed before startup are
not replayed. Use the following diagnostic command to include them:

```powershell
.\.venv\Scripts\xianyu-msg.exe --config config.json monitor --once --include-existing
```

Non-message Xianyu channels are filtered by default. Add `--all-notifications` only when
diagnosing channel classification.

## Routing and pending queue

The `inbox` command composes notification detection with controlled UI routing:

```powershell
.\.venv\Scripts\xianyu-msg.exe --config config.json inbox --interval 0.5
```

For every new message candidate it:

1. requires exactly one notification title match;
2. opens the notification and requires Xianyu's chat activity;
3. extracts the latest visible left-anchored chat message;
4. appends one idempotent record to `var/inbound-pending.jsonl`;
5. records hash-only queue and notification state;
6. presses Home and verifies the focused window through Android `dumpsys window`.

Notification acknowledgement happens only after successful queueing. A routing or extraction
failure therefore remains eligible for a later retry. The workflow never enters text or clicks
Send.

## Output

Each event contains:

- SHA-256 fingerprints instead of the Android notification source key;
- package, channel, category, and Android update time;
- locally observed time;
- title, text, and expanded text when exposed by Android;
- `message_candidate`, based on the configured chat channel or standard message metadata.

The state file contains hashes only. The JSONL event log contains notification text and must be
treated as private local data; `var/` is ignored by Git.

## Limits

- ADB must stay connected.
- Android and Xianyu notification permission must remain enabled.
- Polling can miss a notification that is posted and removed entirely between polls.
- Xianyu may aggregate several messages into one updated notification.
- Xianyu exposes a generic `发来一条新消息` notification instead of the message body.
- Opening the notification can resolve the exact chat, but marks that conversation as read.
- Notification detection never triggers a reply.
- The current extractor queues the latest visible incoming bubble per notification. If Xianyu
  aggregates a burst that exceeds the visible chat viewport, intermediate messages may be missed.
- Masked sender titles must be unique in the notification shade; ambiguous titles fail closed.

The durable production replacement is a small Android companion app based on
`NotificationListenerService`. Android requires the user to grant notification-listener access;
the service then receives notification posted and removed callbacks directly.
