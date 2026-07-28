from __future__ import annotations

import json
import os
import tempfile
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import NotificationEvent
from .notifications import NotificationSource


class NotificationStateStore:
    def __init__(self, path: Path, max_entries: int = 5000):
        self.path = path
        self.max_entries = max_entries

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "seen": {}}
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if data.get("version") != 1 or not isinstance(data.get("seen"), dict):
            raise ValueError(f"unsupported notification state file: {self.path}")
        return data

    def unseen(self, events: list[NotificationEvent]) -> list[NotificationEvent]:
        seen = self._read()["seen"]
        return [event for event in events if event.fingerprint not in seen]

    def record(self, events: list[NotificationEvent]) -> None:
        if not events:
            return
        data = self._read()
        seen = data["seen"]
        recorded_at = datetime.now(UTC).isoformat()
        for event in events:
            seen[event.fingerprint] = recorded_at
        if len(seen) > self.max_entries:
            data["seen"] = dict(list(seen.items())[-self.max_entries :])
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
            os.replace(temporary, self.path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise


class JsonlEventSink:
    def __init__(self, path: Path):
        self.path = path

    def write(self, events: list[NotificationEvent]) -> None:
        if not events:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            for event in events:
                handle.write(json.dumps(event.to_dict(), ensure_ascii=False))
                handle.write("\n")


class NotificationMonitor:
    def __init__(
        self,
        source: NotificationSource,
        state: NotificationStateStore,
        sink: JsonlEventSink,
    ):
        self.source = source
        self.state = state
        self.sink = sink

    def poll(
        self,
        *,
        emit_existing: bool = True,
        message_only: bool = True,
    ) -> list[NotificationEvent]:
        snapshot = self.source.snapshot()
        unseen = self.state.unseen(snapshot)
        self.state.record(snapshot)
        emitted = unseen if emit_existing else []
        if message_only:
            emitted = [event for event in emitted if event.message_candidate]
        self.sink.write(emitted)
        return emitted

    def watch(
        self,
        *,
        interval_seconds: float,
        duration_seconds: float | None = None,
        include_existing: bool = False,
        message_only: bool = True,
    ) -> Iterator[NotificationEvent]:
        for event in self.poll(
            emit_existing=include_existing,
            message_only=message_only,
        ):
            yield event

        deadline = (
            time.monotonic() + duration_seconds
            if duration_seconds is not None
            else None
        )
        while deadline is None or time.monotonic() < deadline:
            time.sleep(interval_seconds)
            for event in self.poll(message_only=message_only):
                yield event
