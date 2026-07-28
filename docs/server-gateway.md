# Server gateway integration

## Responsibility boundary

This repository is the Android transport gateway only:

- detect a new message notification;
- open the exact chat and extract the latest inbound body;
- deliver an idempotent event to `xianyu-auto-reply-fix`;
- send one text decision in the still-open chat;
- report the outcome.

All buyer, item, blacklist, filter, keyword, default, and AI policy remains in
`xianyu-auto-reply-fix`.

## Configuration

Copy the `gateway` object from `config.example.json` into the private `config.json`.

- `base_url`: the server Tailscale URL, currently `http://100.96.121.55:9090`;
- `account_id`: the Cookie ID of the same owned Xianyu account in the server dashboard;
- `device_id`: a stable name for this phone;
- `shared_secret_env`: environment variable containing the shared secret;
- `state_file`: private crash-recovery ledger;
- `notification_state_file`: notification acknowledgement ledger.

The secret is supplied only through the environment:

```powershell
$env:ANDROID_GATEWAY_SHARED_SECRET = "same-random-secret-as-server"
```

The server must list the same `account_id` in `ANDROID_GATEWAY_ACCOUNT_IDS`. That account must be
imported, enabled, and running so the server can actively pull recent conversations for
correlation.

## Run

```powershell
.\.venv\Scripts\xianyu-msg.exe --config config.json gateway --interval 0.5
```

The first notification snapshot is a baseline. For a controlled test of the currently visible
notification:

```powershell
.\.venv\Scripts\xianyu-msg.exe --config config.json gateway --once --include-existing
```

## Failure behavior

- server unavailable before opening: the notification is not opened;
- failure after opening: the chat remains open and the recovery ledger remains pending;
- restart with a pending event: the normal gateway command resumes it before polling;
- crash at the Send boundary: report `send_unconfirmed` and never re-click automatically;
- non-unique server correlation: no reply;
- image decision: `unsupported`, no text or Send interaction;
- duplicate event or receipt: the server returns cached state without repeating business effects.

The current command is intentionally single-device and single-in-flight. A process supervisor
should restart it after transient failures.
