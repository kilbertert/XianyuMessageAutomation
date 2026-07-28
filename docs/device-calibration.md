# Device calibration

The example coordinates were measured on a Xiaomi 13 at 1080 × 2400 with Xianyu 7.19.70.

## Before a live send

1. Enable both `USB debugging` and `USB debugging (Security settings)`.
2. Run `xianyu-msg doctor`.
3. Run `xianyu-msg screenshot-list --output var/message-list.png`.
4. Read the center Y coordinate of the intended visible conversation.
5. Run `reply` without `--apply`.
6. Only add `--apply` after `dry_run_ready`.

## Coordinate meanings

- `message_tab`: message tab center when the normal page is visible.
- `conversation_x`: horizontal point used with the supplied conversation Y coordinate.
- `input`: chat input center before the keyboard opens.
- `candidate_commit`: system IME candidate area used to commit non-ASCII text.
- `send`: yellow Xianyu Send button after the keyboard opens.

All configured points except the conversation Y coordinate are ratios of display width/height.

## Recalibration triggers

Recalibrate after any of the following:

- Xianyu upgrade;
- keyboard or keyboard-layout change;
- display resolution or font-scale change;
- Android system update;
- a different phone model.

Never compensate for a mismatch by repeatedly clicking Send.
