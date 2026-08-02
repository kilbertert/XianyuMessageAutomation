# Device calibration

The example coordinates were measured on a Xiaomi 13 at 1080 × 2400 with Xianyu 7.19.70.

## Before a live send

1. Enable both `USB debugging` and `USB debugging (Security settings)`.
2. During attended setup, install uiautomator2's `AdbKeyboard` and approve the APK prompt on the phone.
3. Switch back to the preferred system keyboard after the installation succeeds.
4. Run `xianyu-msg doctor`.
5. Run `xianyu-msg screenshot-list --output var/message-list.png`.
6. Read the center Y coordinate of the intended visible conversation.
7. Run `reply` without `--apply`.
8. Only add `--apply` after `dry_run_ready`.

The resident gateway refuses to trigger an unattended APK installation. Install the
keyboard once with the phone unlocked, then keep the package installed:

```powershell
.\.venv\Scripts\python.exe -c "import uiautomator2 as u2; u2.connect('DEVICE_SERIAL').set_input_ime(True)"
```

## Coordinate meanings

- `message_tab`: message tab center when the normal page is visible.
- `conversation_x`: horizontal point used with the supplied conversation Y coordinate.
- `input`: chat input center before the keyboard opens.
- `candidate_commit`: retained for configuration compatibility; gateway replies use AdbKeyboard.
- `send`: yellow Xianyu Send button after AdbKeyboard hides the keyboard.

All configured points except the conversation Y coordinate are ratios of display width/height.

## Recalibration triggers

Recalibrate after any of the following:

- Xianyu upgrade;
- keyboard or keyboard-layout change;
- display resolution or font-scale change;
- Android system update;
- a different phone model.

Never compensate for a mismatch by repeatedly clicking Send.
