from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from .errors import DeviceStateError
from .models import (
    InboundMessage,
    InboundResult,
    InboundStatus,
    NotificationEvent,
    TextNode,
)
from .monitor import NotificationStateStore
from .notifications import NotificationSource
from .parser import text_nodes


def incoming_chat_messages(xml: str, *, width: int, height: int) -> list[TextNode]:
    messages: list[TextNode] = []
    for node in text_nodes(xml):
        bounds = node.bounds
        if (
            bounds is None
            or node.class_name != "android.view.View"
            or not node.clickable
        ):
            continue
        if bounds.top < height * 0.2 or bounds.bottom > height * 0.85:
            continue
        if bounds.left > width * 0.25 or bounds.right >= width * 0.8:
            continue
        messages.append(node)
    return sorted(messages, key=lambda node: node.bounds.bottom if node.bounds else 0)


class InboundDevicePort(Protocol):
    def open_notification(self, title: str) -> str: ...

    def display_size(self) -> tuple[int, int]: ...

    def return_home(self) -> None: ...


class InboundQueue:
    def __init__(self, state_file: Path, queue_file: Path):
        self.state_file = state_file
        self.queue_file = queue_file

    def _read_state(self) -> dict[str, Any]:
        if not self.state_file.exists():
            return {"version": 1, "queued": {}}
        data = json.loads(self.state_file.read_text(encoding="utf-8"))
        if data.get("version") != 1 or not isinstance(data.get("queued"), dict):
            raise ValueError(f"unsupported inbound state file: {self.state_file}")
        return data

    def _write_state(self, data: dict[str, Any]) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{self.state_file.name}.",
            suffix=".tmp",
            dir=self.state_file.parent,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
            os.replace(temporary, self.state_file)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise

    def _queue_contains(self, fingerprint: str) -> bool:
        if not self.queue_file.exists():
            return False
        for line in self.queue_file.read_text(encoding="utf-8").splitlines():
            if json.loads(line).get("fingerprint") == fingerprint:
                return True
        return False

    def enqueue(self, message: InboundMessage) -> bool:
        state = self._read_state()
        if (
            message.fingerprint in state["queued"]
            or self._queue_contains(message.fingerprint)
        ):
            return False

        self.queue_file.parent.mkdir(parents=True, exist_ok=True)
        with self.queue_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(message.to_dict(), ensure_ascii=False))
            handle.write("\n")

        state["queued"][message.fingerprint] = message.queued_at
        self._write_state(state)
        return True


class InboundWorkflow:
    def __init__(self, device: InboundDevicePort, queue: InboundQueue):
        self.device = device
        self.queue = queue

    def process(self, event: NotificationEvent) -> InboundResult:
        if not event.message_candidate:
            raise DeviceStateError("notification is not a message candidate")
        if not event.title:
            raise DeviceStateError("message notification has no sender title")

        xml = self.device.open_notification(event.title)
        try:
            width, height = self.device.display_size()
            candidates = incoming_chat_messages(xml, width=width, height=height)
            if not candidates:
                raise DeviceStateError("no incoming chat message was exposed")
            body = candidates[-1].value
            fingerprint = hashlib.sha256(
                f"{event.fingerprint}\0{body}".encode("utf-8")
            ).hexdigest()
            queued_at = datetime.now(UTC).isoformat()
            message = InboundMessage(
                fingerprint=fingerprint,
                notification_fingerprint=event.fingerprint,
                sender=event.title,
                body=body,
                observed_at=event.observed_at,
                queued_at=queued_at,
            )
            queued = self.queue.enqueue(message)
            return InboundResult(
                status=(
                    InboundStatus.QUEUED
                    if queued
                    else InboundStatus.SKIPPED_DUPLICATE
                ),
                fingerprint=fingerprint,
                sender=event.title,
                body=body,
            )
        finally:
            self.device.return_home()


class InboundPoller:
    def __init__(
        self,
        source: NotificationSource,
        state: NotificationStateStore,
        workflow: InboundWorkflow,
    ):
        self.source = source
        self.state = state
        self.workflow = workflow

    def poll(self, *, include_existing: bool = True) -> list[InboundResult]:
        snapshot = self.source.snapshot()
        unseen = self.state.unseen(snapshot)
        if not include_existing:
            self.state.record(snapshot)
            return []

        results: list[InboundResult] = []
        for event in unseen:
            if not event.message_candidate:
                self.state.record([event])
                continue
            result = self.workflow.process(event)
            self.state.record([event])
            results.append(result)
        return results

    def watch(
        self,
        *,
        interval_seconds: float,
        duration_seconds: float | None = None,
        include_existing: bool = False,
    ) -> Iterator[InboundResult]:
        yield from self.poll(include_existing=include_existing)
        deadline = (
            time.monotonic() + duration_seconds
            if duration_seconds is not None
            else None
        )
        while deadline is None or time.monotonic() < deadline:
            time.sleep(interval_seconds)
            yield from self.poll()
