from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def fingerprint(marker: str, conversation_hint: str) -> str:
    payload = f"{conversation_hint}\0{marker.casefold()}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class StateStore:
    def __init__(self, path: Path):
        self.path = path

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "processed": {}}
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if data.get("version") != 1 or not isinstance(data.get("processed"), dict):
            raise ValueError(f"unsupported state file: {self.path}")
        return data

    def contains(self, key: str) -> bool:
        return key in self._read()["processed"]

    def record_sent(self, key: str, reply: str) -> None:
        data = self._read()
        data["processed"][key] = {
            "sent_at": datetime.now(UTC).isoformat(),
            "reply_sha256": hashlib.sha256(reply.encode("utf-8")).hexdigest(),
        }
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
