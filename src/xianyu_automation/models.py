from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any


@dataclass(frozen=True)
class Bounds:
    left: int
    top: int
    right: int
    bottom: int


@dataclass(frozen=True)
class TextNode:
    value: str
    bounds: Bounds | None
    class_name: str
    clickable: bool


class ReplyStatus(StrEnum):
    DRY_RUN_READY = "dry_run_ready"
    SENT = "sent"
    SKIPPED_DUPLICATE = "skipped_duplicate"
    TARGET_MISSING = "target_missing"
    TARGET_NOT_UNIQUE = "target_not_unique"
    SEND_UNCONFIRMED = "send_unconfirmed"


@dataclass(frozen=True)
class ReplyRequest:
    marker: str
    reply: str
    apply: bool = False
    conversation_y: int | None = None
    current_chat: bool = False
    keep_artifacts: bool = False


@dataclass(frozen=True)
class ReplyResult:
    status: ReplyStatus
    marker_count: int
    reply_count: int
    sent_clicks: int
    fingerprint: str
    unread_before: int | None = None
    unread_after: int | None = None
    artifacts: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["status"] = self.status.value
        result["artifacts"] = list(self.artifacts)
        return result


@dataclass(frozen=True)
class NotificationEvent:
    fingerprint: str
    source_key_sha256: str
    package: str
    channel: str | None
    category: str | None
    update_time_ms: int | None
    observed_at: str
    title: str | None
    text: str | None
    big_text: str | None
    message_candidate: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class InboundStatus(StrEnum):
    QUEUED = "queued"
    SKIPPED_DUPLICATE = "skipped_duplicate"


class GatewayStatus(StrEnum):
    SENT = "sent"
    NO_REPLY = "no_reply"
    SKIPPED_DUPLICATE = "skipped_duplicate"
    UNSUPPORTED = "unsupported"
    SEND_UNCONFIRMED = "send_unconfirmed"


@dataclass(frozen=True)
class InboundMessage:
    fingerprint: str
    notification_fingerprint: str
    sender: str
    body: str
    observed_at: str
    queued_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class InboundResult:
    status: InboundStatus
    fingerprint: str
    sender: str
    body: str
    sent_clicks: int = 0

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["status"] = self.status.value
        return result


@dataclass(frozen=True)
class GatewayResult:
    status: GatewayStatus
    event_id: str
    sender: str
    body: str
    decision_source: str | None = None
    reason: str | None = None
    sent_clicks: int = 0

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["status"] = self.status.value
        return result
