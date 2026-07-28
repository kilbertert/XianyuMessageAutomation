from __future__ import annotations

import hashlib
import re
import subprocess
from datetime import UTC, datetime
from typing import Protocol

from .config import AutomationConfig
from .errors import DeviceStateError
from .models import NotificationEvent

_RECORD = re.compile(
    r"(?ms)^\s*NotificationRecord\(.*?(?=^\s*NotificationRecord\(|\Z)"
)
_EXTRA = re.compile(
    r"(?m)^\s*(android\.(?:title|text|bigText|template))="
    r"[^\s]+\s+\((.*)\)\s*$"
)


class NotificationSource(Protocol):
    def snapshot(self) -> list[NotificationEvent]: ...


def _match(pattern: str, value: str) -> str | None:
    match = re.search(pattern, value)
    return match.group(1) if match else None


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return None if not cleaned or cleaned == "null" else cleaned


def parse_notification_dump(
    dump: str,
    package: str,
    *,
    observed_at: str | None = None,
    message_channel_ids: tuple[str, ...] = (),
) -> list[NotificationEvent]:
    observed = observed_at or datetime.now(UTC).isoformat()
    events: list[NotificationEvent] = []

    for match in _RECORD.finditer(dump):
        block = match.group(0)
        record_package = _match(r"\bpkg=([^\s]+)", block)
        if record_package != package:
            continue

        source_key = _match(r"\bkey=([^\s]+)", block) or ""
        channel = _clean(_match(r"Notification\(channel=([^\s]+)", block))
        category = _clean(_match(r"\bcategory=([^\s\)]+)", block))
        update_raw = _match(r"\bmUpdateTimeMs=(\d+)", block)
        if update_raw is None:
            update_raw = _match(r"\bmCreationTimeMs=(\d+)", block)
        update_time_ms = int(update_raw) if update_raw else None

        extras = {
            extra.group(1): _clean(extra.group(2))
            for extra in _EXTRA.finditer(block)
        }
        title = extras.get("android.title")
        text = extras.get("android.text")
        big_text = extras.get("android.bigText")
        template = extras.get("android.template") or ""

        classification = " ".join(
            item for item in (category, channel, template) if item
        ).casefold()
        message_candidate = (
            channel in message_channel_ids
            or category == "msg"
            or any(token in classification for token in ("message", "chat", "im_"))
        )

        source_key_hash = hashlib.sha256(source_key.encode("utf-8")).hexdigest()
        identity = "\0".join(
            (
                source_key,
                str(update_time_ms or ""),
                title or "",
                text or "",
                big_text or "",
            )
        )
        event_fingerprint = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        events.append(
            NotificationEvent(
                fingerprint=event_fingerprint,
                source_key_sha256=source_key_hash,
                package=record_package,
                channel=channel,
                category=category,
                update_time_ms=update_time_ms,
                observed_at=observed,
                title=title,
                text=text,
                big_text=big_text,
                message_candidate=message_candidate,
            )
        )

    return events


class AdbNotificationSource:
    def __init__(self, config: AutomationConfig):
        self.config = config

    def snapshot(self) -> list[NotificationEvent]:
        process = subprocess.run(
            [
                self.config.adb_path,
                "-s",
                self.config.serial,
                "shell",
                "dumpsys",
                "notification",
                "--noredact",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if process.returncode != 0:
            detail = process.stderr.strip() or "unknown adb error"
            raise DeviceStateError(f"cannot read Android notifications: {detail}")
        return parse_notification_dump(
            process.stdout,
            self.config.app.package,
            message_channel_ids=self.config.notifications.message_channel_ids,
        )
