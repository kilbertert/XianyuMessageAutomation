from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from .config import AutomationConfig
from .device import DevicePort
from .models import ReplyRequest, ReplyResult, ReplyStatus
from .parser import find_text, unread_count
from .store import StateStore, fingerprint


class ReplyWorkflow:
    def __init__(
        self,
        config: AutomationConfig,
        device: DevicePort,
        store: StateStore,
    ):
        self.config = config
        self.device = device
        self.store = store

    def run(self, request: ReplyRequest) -> ReplyResult:
        marker = request.marker.strip()
        reply = request.reply.strip()
        if not marker:
            raise ValueError("marker must not be empty")
        if not reply:
            raise ValueError("reply must not be empty")
        if request.current_chat == (request.conversation_y is not None):
            raise ValueError("choose exactly one of current_chat or conversation_y")

        unread_before: int | None = None
        if request.current_chat:
            self.device.ensure_chat()
            conversation_hint = "current-chat"
        else:
            list_xml = self.device.navigate_to_messages()
            unread_before = unread_count(list_xml)
            assert request.conversation_y is not None
            self.device.open_conversation(request.conversation_y)
            conversation_hint = f"row-y:{request.conversation_y}"

        chat_xml = self.device.dump_hierarchy()
        marker_count = len(find_text(chat_xml, marker))
        reply_count = len(find_text(chat_xml, reply, case_sensitive=True))
        key = fingerprint(marker, conversation_hint)

        if marker_count == 0:
            return ReplyResult(
                status=ReplyStatus.TARGET_MISSING,
                marker_count=0,
                reply_count=reply_count,
                sent_clicks=0,
                fingerprint=key,
                unread_before=unread_before,
            )
        if marker_count != 1:
            return ReplyResult(
                status=ReplyStatus.TARGET_NOT_UNIQUE,
                marker_count=marker_count,
                reply_count=reply_count,
                sent_clicks=0,
                fingerprint=key,
                unread_before=unread_before,
            )
        if reply_count or self.store.contains(key):
            return ReplyResult(
                status=ReplyStatus.SKIPPED_DUPLICATE,
                marker_count=marker_count,
                reply_count=reply_count,
                sent_clicks=0,
                fingerprint=key,
                unread_before=unread_before,
            )
        if not request.apply:
            return ReplyResult(
                status=ReplyStatus.DRY_RUN_READY,
                marker_count=marker_count,
                reply_count=0,
                sent_clicks=0,
                fingerprint=key,
                unread_before=unread_before,
            )

        artifacts: list[str] = []
        draft_path: Path | None = None
        if request.keep_artifacts:
            run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            run_dir = self.config.artifact_dir / run_id
            draft_path = run_dir / "draft.png"
            artifacts.append(str(draft_path))

        self.device.prepare_reply(reply, draft_path)
        self.device.send_once()
        confirmed = self.device.wait_for_text(reply)
        if confirmed != 1:
            return ReplyResult(
                status=ReplyStatus.SEND_UNCONFIRMED,
                marker_count=marker_count,
                reply_count=confirmed,
                sent_clicks=1,
                fingerprint=key,
                unread_before=unread_before,
                artifacts=tuple(artifacts),
            )

        self.store.record_sent(key, reply)
        list_xml = self.device.return_to_messages()
        return ReplyResult(
            status=ReplyStatus.SENT,
            marker_count=marker_count,
            reply_count=confirmed,
            sent_clicks=1,
            fingerprint=key,
            unread_before=unread_before,
            unread_after=unread_count(list_xml),
            artifacts=tuple(artifacts),
        )
