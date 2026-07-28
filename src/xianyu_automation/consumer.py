from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


class QueueConsumer:
    def __init__(self, queue_file: Path, state_file: Path):
        self.queue_file = queue_file
        self.state_file = state_file

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        lock_file = self.state_file.with_name(f"{self.state_file.name}.lock")
        with lock_file.open("a+b") as handle:
            if os.name == "nt":
                import msvcrt

                handle.seek(0, os.SEEK_END)
                if handle.tell() == 0:
                    handle.write(b"\0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                try:
                    yield
                finally:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _read_state(self) -> dict[str, Any]:
        if not self.state_file.exists():
            return {"version": 1, "messages": {}}
        data = json.loads(self.state_file.read_text(encoding="utf-8"))
        if data.get("version") != 1 or not isinstance(data.get("messages"), dict):
            raise ValueError(f"unsupported consumer state file: {self.state_file}")
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

    def _messages(self) -> list[dict[str, Any]]:
        if not self.queue_file.exists():
            return []
        return [
            json.loads(line)
            for line in self.queue_file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def _owned_entry(
        self,
        state: dict[str, Any],
        fingerprint: str,
        worker_id: str,
        current: datetime,
    ) -> dict[str, Any]:
        entry = state["messages"].get(fingerprint)
        if entry is None or entry.get("status") != "processing":
            raise ValueError(f"message is not processing: {fingerprint}")
        if entry.get("worker_id") != worker_id:
            raise ValueError(f"message lease is owned by another worker: {fingerprint}")
        if datetime.fromisoformat(entry["lease_until"]) <= current:
            raise ValueError(f"message lease has expired: {fingerprint}")
        return entry

    def claim(
        self,
        worker_id: str,
        *,
        lease_seconds: int,
        now: datetime | None = None,
    ) -> dict[str, Any] | None:
        worker_id = worker_id.strip()
        if not worker_id:
            raise ValueError("worker_id must not be empty")
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        current = now or datetime.now(UTC)
        if current.tzinfo is None:
            raise ValueError("now must be timezone-aware")

        with self._locked():
            state = self._read_state()
            for message in self._messages():
                fingerprint = str(message.get("fingerprint", "")).strip()
                if not fingerprint:
                    raise ValueError("queue message is missing fingerprint")
                entry = state["messages"].get(fingerprint)
                if entry is not None:
                    status = entry.get("status")
                    if status in {"done", "dead"}:
                        continue
                    if status == "processing":
                        lease_until = datetime.fromisoformat(entry["lease_until"])
                        if lease_until > current:
                            continue

                attempts = int(entry.get("attempts", 0)) + 1 if entry else 1
                lease_until = current + timedelta(seconds=lease_seconds)
                state["messages"][fingerprint] = {
                    "status": "processing",
                    "attempts": attempts,
                    "worker_id": worker_id,
                    "lease_until": lease_until.isoformat(),
                    "updated_at": current.isoformat(),
                }
                self._write_state(state)
                return {
                    "message": message,
                    "attempts": attempts,
                    "worker_id": worker_id,
                    "lease_until": lease_until.isoformat(),
                }
        return None

    def ack(
        self,
        fingerprint: str,
        worker_id: str,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        current = now or datetime.now(UTC)
        if current.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        with self._locked():
            state = self._read_state()
            entry = self._owned_entry(state, fingerprint, worker_id, current)

            completed_at = current.isoformat()
            result = {
                "fingerprint": fingerprint,
                "status": "done",
                "attempts": int(entry["attempts"]),
                "completed_at": completed_at,
            }
            state["messages"][fingerprint] = {
                "status": "done",
                "attempts": result["attempts"],
                "completed_at": completed_at,
                "updated_at": completed_at,
            }
            self._write_state(state)
            return result

    def fail(
        self,
        fingerprint: str,
        worker_id: str,
        reason: str,
        *,
        max_attempts: int,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if max_attempts <= 0:
            raise ValueError("max_attempts must be positive")
        if not reason:
            raise ValueError("reason must not be empty")
        current = now or datetime.now(UTC)
        if current.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        with self._locked():
            state = self._read_state()
            entry = self._owned_entry(state, fingerprint, worker_id, current)

            attempts = int(entry["attempts"])
            status = "dead" if attempts >= max_attempts else "pending"
            failed_at = current.isoformat()
            result = {
                "fingerprint": fingerprint,
                "status": status,
                "attempts": attempts,
                "failed_at": failed_at,
                "last_error_sha256": hashlib.sha256(
                    reason.encode("utf-8")
                ).hexdigest(),
            }
            state["messages"][fingerprint] = {
                "status": status,
                "attempts": attempts,
                "failed_at": failed_at,
                "last_error_sha256": result["last_error_sha256"],
                "updated_at": failed_at,
            }
            self._write_state(state)
            return result
