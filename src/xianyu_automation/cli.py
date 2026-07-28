from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import load_config
from .consumer import QueueConsumer
from .device import Uiautomator2Device
from .doctor import AdbDoctor
from .errors import AutomationError
from .gateway import GatewayClient, GatewayDeliveryStore, GatewayWorkflow
from .inbound import InboundPoller, InboundQueue, InboundWorkflow
from .models import GatewayStatus, ReplyRequest, ReplyStatus
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

    inbox = subcommands.add_parser(
        "inbox",
        help="route new Xianyu notifications and queue the latest inbound body",
    )
    inbox_mode = inbox.add_mutually_exclusive_group()
    inbox_mode.add_argument("--once", action="store_true", help="read one notification snapshot")
    inbox_mode.add_argument("--duration", type=float, help="watch for this many seconds")
    inbox.add_argument("--interval", type=float, help="poll interval in seconds")
    inbox.add_argument(
        "--include-existing",
        action="store_true",
        help="route active notifications on the first snapshot",
    )

    gateway = subcommands.add_parser(
        "gateway",
        help="route new messages to the business server and send its reply decision",
    )
    gateway_mode = gateway.add_mutually_exclusive_group()
    gateway_mode.add_argument(
        "--once",
        action="store_true",
        help="read one notification snapshot",
    )
    gateway_mode.add_argument(
        "--duration",
        type=float,
        help="watch for this many seconds",
    )
    gateway.add_argument("--interval", type=float, help="poll interval in seconds")
    gateway.add_argument(
        "--include-existing",
        action="store_true",
        help="route active notifications on the first snapshot",
    )
    gateway.add_argument(
        "--resume-current",
        action="store_true",
        help="resume the durable in-flight event in the already open chat",
    )

    queue = subcommands.add_parser(
        "queue",
        help="claim and settle records from the inbound pending queue",
    )
    queue_actions = queue.add_subparsers(dest="queue_action", required=True)
    claim = queue_actions.add_parser("claim", help="lease the oldest available message")
    claim.add_argument("--worker-id", required=True, help="stable consumer worker identifier")
    claim.add_argument(
        "--lease-seconds",
        type=int,
        default=300,
        help="seconds before an unacknowledged claim can be redelivered",
    )
    ack = queue_actions.add_parser("ack", help="mark an owned claim as completed")
    ack.add_argument("--worker-id", required=True, help="claim owner identifier")
    ack.add_argument("--fingerprint", required=True, help="claimed message fingerprint")
    fail = queue_actions.add_parser("fail", help="release or dead-letter an owned claim")
    fail.add_argument("--worker-id", required=True, help="claim owner identifier")
    fail.add_argument("--fingerprint", required=True, help="claimed message fingerprint")
    fail.add_argument("--reason", required=True, help="failure reason; only its hash is stored")
    fail.add_argument(
        "--max-attempts",
        type=int,
        default=3,
        help="dead-letter the message after this many claims",
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


def _configure_stdout() -> None:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    _configure_stdout()
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

        if args.command == "inbox":
            interval = args.interval or config.notifications.poll_seconds
            if interval <= 0:
                raise ValueError("inbox interval must be positive")
            if args.duration is not None and args.duration <= 0:
                raise ValueError("inbox duration must be positive")
            workflow = InboundWorkflow(
                Uiautomator2Device(config),
                InboundQueue(
                    config.inbound.queue_state_file,
                    config.inbound.queue_file,
                ),
            )
            poller = InboundPoller(
                AdbNotificationSource(config),
                NotificationStateStore(config.inbound.notification_state_file),
                workflow,
            )
            queued = 0
            if args.once:
                results = poller.poll(include_existing=args.include_existing)
                for result in results:
                    print(
                        json.dumps(
                            {"type": "xianyu_inbound", **result.to_dict()},
                            ensure_ascii=False,
                        ),
                        flush=True,
                    )
                    queued += result.status == "queued"
            else:
                try:
                    stream = poller.watch(
                        interval_seconds=interval,
                        duration_seconds=args.duration,
                        include_existing=args.include_existing,
                    )
                    for result in stream:
                        print(
                            json.dumps(
                                {"type": "xianyu_inbound", **result.to_dict()},
                                ensure_ascii=False,
                            ),
                            flush=True,
                        )
                        queued += result.status == "queued"
                except KeyboardInterrupt:
                    pass
            _print(
                {
                    "type": "summary",
                    "queued": queued,
                    "queue_file": str(config.inbound.queue_file),
                }
            )
            return 0

        if args.command == "gateway":
            if config.gateway is None:
                raise ValueError("gateway configuration is missing")
            interval = args.interval or config.notifications.poll_seconds
            if interval <= 0:
                raise ValueError("gateway interval must be positive")
            if args.duration is not None and args.duration <= 0:
                raise ValueError("gateway duration must be positive")

            device = Uiautomator2Device(config)
            store = GatewayDeliveryStore(config.gateway.state_file)
            workflow = GatewayWorkflow(
                config,
                device,
                GatewayClient(config.gateway),
                store,
            )

            if args.resume_current:
                result = workflow.resume()
                _print({"type": "xianyu_gateway", **result.to_dict()})
                return (
                    0
                    if result.status
                    in {
                        GatewayStatus.SENT,
                        GatewayStatus.NO_REPLY,
                        GatewayStatus.SKIPPED_DUPLICATE,
                    }
                    else 2
                )

            if store.pending() is not None:
                resumed = workflow.resume()
                print(
                    json.dumps(
                        {"type": "xianyu_gateway", **resumed.to_dict()},
                        ensure_ascii=False,
                    ),
                    flush=True,
                )

            poller = InboundPoller(
                AdbNotificationSource(config),
                NotificationStateStore(
                    config.gateway.notification_state_file
                ),
                workflow,
            )
            processed = 0
            sent = 0
            no_reply = 0
            if args.once:
                results = poller.poll(include_existing=args.include_existing)
                for result in results:
                    print(
                        json.dumps(
                            {"type": "xianyu_gateway", **result.to_dict()},
                            ensure_ascii=False,
                        ),
                        flush=True,
                    )
                    processed += 1
                    sent += result.status == GatewayStatus.SENT
                    no_reply += result.status == GatewayStatus.NO_REPLY
            else:
                try:
                    stream = poller.watch(
                        interval_seconds=interval,
                        duration_seconds=args.duration,
                        include_existing=args.include_existing,
                    )
                    for result in stream:
                        print(
                            json.dumps(
                                {"type": "xianyu_gateway", **result.to_dict()},
                                ensure_ascii=False,
                            ),
                            flush=True,
                        )
                        processed += 1
                        sent += result.status == GatewayStatus.SENT
                        no_reply += result.status == GatewayStatus.NO_REPLY
                except KeyboardInterrupt:
                    pass
            _print(
                {
                    "type": "summary",
                    "processed": processed,
                    "sent": sent,
                    "no_reply": no_reply,
                    "gateway": config.gateway.base_url,
                }
            )
            return 0

        if args.command == "queue":
            consumer = QueueConsumer(
                config.inbound.queue_file,
                config.inbound.consumer_state_file,
            )
            if args.queue_action == "claim":
                claim = consumer.claim(
                    args.worker_id,
                    lease_seconds=args.lease_seconds,
                )
                _print(
                    {
                        "type": "xianyu_queue_claim",
                        "claimed": claim is not None,
                        **(claim or {}),
                    }
                )
                return 0
            if args.queue_action == "ack":
                result = consumer.ack(args.fingerprint, args.worker_id)
                _print({"type": "xianyu_queue_ack", **result})
                return 0
            if args.queue_action == "fail":
                result = consumer.fail(
                    args.fingerprint,
                    args.worker_id,
                    args.reason,
                    max_attempts=args.max_attempts,
                )
                _print({"type": "xianyu_queue_fail", **result})
                return 0
            raise AssertionError(f"unhandled queue action: {args.queue_action}")

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
