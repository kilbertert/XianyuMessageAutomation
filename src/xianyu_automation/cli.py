from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import load_config
from .device import Uiautomator2Device
from .doctor import AdbDoctor
from .errors import AutomationError
from .models import ReplyRequest, ReplyStatus
from .monitor import JsonlEventSink, NotificationMonitor, NotificationStateStore
from .notifications import AdbNotificationSource
from .parser import unread_count
from .store import StateStore
from .workflow import ReplyWorkflow


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="xianyu-msg",
        description="Controlled Android automation for Xianyu messages.",
    )
    parser.add_argument("--config", default="config.json", help="path to JSON configuration")
    subcommands = parser.add_subparsers(dest="command", required=True)

    subcommands.add_parser("doctor", help="check ADB, device input permission and app version")
    subcommands.add_parser("unread", help="open the message page and report the unread count")

    screenshot = subcommands.add_parser(
        "screenshot-list", help="capture the message list for local row calibration"
    )
    screenshot.add_argument("--output", required=True, help="PNG output path")

    monitor = subcommands.add_parser(
        "monitor", help="watch Android notifications for new Xianyu events"
    )
    mode = monitor.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="read one notification snapshot")
    mode.add_argument("--duration", type=float, help="watch for this many seconds")
    monitor.add_argument("--interval", type=float, help="poll interval in seconds")
    monitor.add_argument(
        "--include-existing",
        action="store_true",
        help="emit active notifications on the first snapshot",
    )
    monitor.add_argument(
        "--all-notifications",
        action="store_true",
        help="include non-message Xianyu notifications for diagnostics",
    )

    reply = subcommands.add_parser(
        "reply", help="verify a marker and optionally send exactly one reply"
    )
    reply.add_argument("--marker", required=True, help="unique incoming message marker")
    reply.add_argument("--reply", required=True, help="reply text")
    destination = reply.add_mutually_exclusive_group(required=True)
    destination.add_argument("--conversation-y", type=int, help="visible conversation row y")
    destination.add_argument(
        "--current-chat", action="store_true", help="the target chat is already open"
    )
    reply.add_argument(
        "--apply",
        action="store_true",
        help="perform the send; without this flag the command is a dry-run",
    )
    reply.add_argument(
        "--keep-artifacts",
        action="store_true",
        help="retain a private draft screenshot under artifact_dir",
    )
    return parser


def _print(data: object) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        config = load_config(args.config)
        if args.command == "doctor":
            result = AdbDoctor(config).inspect()
            _print(result)
            return 0 if result.get("ok") else 2

        if args.command == "monitor":
            interval = args.interval or config.notifications.poll_seconds
            if interval <= 0:
                raise ValueError("monitor interval must be positive")
            if args.duration is not None and args.duration <= 0:
                raise ValueError("monitor duration must be positive")
            monitor = NotificationMonitor(
                AdbNotificationSource(config),
                NotificationStateStore(config.notifications.state_file),
                JsonlEventSink(config.notifications.event_log),
            )
            emitted = 0
            message_only = not args.all_notifications
            if args.once:
                events = monitor.poll(
                    emit_existing=args.include_existing,
                    message_only=message_only,
                )
                for event in events:
                    print(
                        json.dumps(
                            {"type": "xianyu_message", **event.to_dict()},
                            ensure_ascii=False,
                        ),
                        flush=True,
                    )
                    emitted += 1
            else:
                try:
                    stream = monitor.watch(
                        interval_seconds=interval,
                        duration_seconds=args.duration,
                        include_existing=args.include_existing,
                        message_only=message_only,
                    )
                    for event in stream:
                        print(
                            json.dumps(
                                {"type": "xianyu_message", **event.to_dict()},
                                ensure_ascii=False,
                            ),
                            flush=True,
                        )
                        emitted += 1
                except KeyboardInterrupt:
                    pass
            _print(
                {
                    "type": "summary",
                    "emitted": emitted,
                    "event_log": str(config.notifications.event_log),
                }
            )
            return 0

        device = Uiautomator2Device(config)
        if args.command == "unread":
            _print({"unread": unread_count(device.navigate_to_messages())})
            return 0
        if args.command == "screenshot-list":
            device.navigate_to_messages()
            output = Path(args.output).resolve()
            device.screenshot(output)
            _print({"output": str(output)})
            return 0
        if args.command == "reply":
            workflow = ReplyWorkflow(config, device, StateStore(config.state_file))
            result = workflow.run(
                ReplyRequest(
                    marker=args.marker,
                    reply=args.reply,
                    apply=args.apply,
                    conversation_y=args.conversation_y,
                    current_chat=args.current_chat,
                    keep_artifacts=args.keep_artifacts,
                )
            )
            _print(result.to_dict())
            return (
                0
                if result.status
                in {
                    ReplyStatus.DRY_RUN_READY,
                    ReplyStatus.SENT,
                    ReplyStatus.SKIPPED_DUPLICATE,
                }
                else 2
            )
        raise AssertionError(f"unhandled command: {args.command}")
    except (AutomationError, OSError, ValueError) as exc:
        _print({"ok": False, "error": str(exc)})
        return 2


if __name__ == "__main__":
    sys.exit(main())
