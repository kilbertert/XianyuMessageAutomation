# Architecture

## Scope

The first release implements the Android path that has been verified on a Xiaomi 13:

1. check ADB and input-injection permission;
2. open the Xianyu message page and read the unread badge;
3. open one explicitly selected visible conversation;
4. require one unique incoming marker in the chat accessibility tree;
5. default to dry-run;
6. inject one reply, click Send once, and require one matching outgoing bubble;
7. persist only hashes for duplicate protection.

It does not scan every conversation or send unsolicited messages.

## Components

```text
CLI
 ├─ AdbDoctor             device/app preflight
 ├─ Uiautomator2Device    Android UI adapter
 ├─ UI parser             unread and message-node parsing
 ├─ NotificationSource    incremental Android notification snapshots
 ├─ NotificationMonitor   baseline, deduplication, and JSONL event stream
 ├─ InboundPoller         route-after-detect with acknowledge-after-queue
 ├─ InboundWorkflow       exact notification, body extraction, pending queue
 ├─ ReplyWorkflow         invariants and single-send state machine
 └─ StateStore            atomic hash-only duplicate ledger
```

The workflow depends on `DevicePort`, so tests can prove sending invariants without a phone.

## Safety invariants

- Dry-run is the default.
- A target marker must appear exactly once.
- An existing reply or processed fingerprint blocks another send.
- The Send control is clicked at most once per run.
- A missing post-send bubble is reported as `send_unconfirmed`; it is never retried.
- The state file stores hashes, timestamps, and status only.
- Private screenshots are retained only with `--keep-artifacts`.
- Notification monitoring never opens a conversation or sends a reply.
- Notification source keys and deduplication state are stored as hashes.
- Inbound routing acknowledges a notification only after its body is queued.
- A notification title must match exactly once before any click.
- Inbound routing returns to Home and verifies the focused system window.

## Current device-specific boundary

Xianyu 7.19.70 renders the message list and input controls with Flutter/custom drawing:

- conversation previews are absent from the UI hierarchy;
- chat message bodies are exposed through `content-desc`;
- Chinese text first enters the system IME composition area;
- the candidate must be committed before the app Send button is clicked.

Coordinates therefore live in configuration. They must be recalibrated after an app, device,
resolution, font-scale, or keyboard change.

## Next milestones

1. Native `NotificationListenerService` helper to replace ADB polling.
2. Burst-message reconciliation when Xianyu aggregates several messages.
3. Rule-based response policy and manual escalation.
4. A bounded worker loop with heartbeat, cooldown, and circuit breaker.
5. Regression fixtures for each supported Xianyu version.
