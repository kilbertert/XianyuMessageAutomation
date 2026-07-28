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
 ├─ QueueConsumer         leased claim, explicit acknowledgement, dead letters
 ├─ GatewayWorkflow       synchronous server decision and current-chat delivery
 ├─ GatewayClient         HMAC-signed event and receipt transport over Tailscale
 ├─ GatewayDeliveryStore  crash-recoverable, at-most-once UI-send ledger
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
- A queue record remains pending until its owning worker explicitly acknowledges it.
- Expired leases are redelivered, so consumers must handle messages idempotently.
- Queue claim, acknowledgement, and failure transitions share an OS file lock.
- Repeated failures become dead letters at the configured attempt limit.
- Consumer state stores lifecycle metadata and failure hashes, never sender or body plaintext.
- Gateway events are decided idempotently by the server while Android keeps the exact chat open.
- The Android gateway persists `sending` before touching the input, so recovery never re-clicks Send.
- Gateway HTTP is accepted only over HTTPS, loopback, or a Tailscale address and is HMAC-signed.

## Server gateway flow

```text
Android notification
  -> unique notification title
  -> current chat + latest left-side body
  -> signed idempotent event over Tailscale
  -> server pulls recent IM sessions and requires one exact inbound match
  -> existing item/keyword/default/AI decision chain
  -> Android current-chat text send
  -> signed sent/skipped/unconfirmed receipt
```

The local pending JSONL queue remains available for receive-only integrations. It is not used for
delayed Android replies because, after leaving the chat, the accessibility tree exposes no stable
conversation identifier. The integrated gateway therefore makes the decision synchronously while
the notification-opened chat is still held.

## Pending queue semantics

`var/inbound-pending.jsonl` is an append-only local message log. `QueueConsumer` keeps a separate
hash-keyed state machine in `var/inbound-consumer-state.json`:

```text
unseen/pending -> processing --ack--> done
                       |
                       +--fail below limit--> pending
                       +--fail at limit-----> dead
                       +--lease expires-----> processing on a later claim
```

This provides at-least-once delivery. A worker receives the complete queue record from `claim`,
but the consumer state and lock files contain no message plaintext. The local file-backed design
fits the current single-device deployment and supports concurrent local worker processes; it is
not a distributed broker across multiple hosts.

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
3. Image-reply support through a separately verified Android picker flow.
4. A Windows service wrapper with heartbeat and alerting.
5. Regression fixtures for each supported Xianyu version.
