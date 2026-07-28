from pathlib import Path

from xianyu_automation.config import (
    AppSettings,
    AutomationConfig,
    CoordinateSettings,
    InboundSettings,
    NotificationSettings,
    TimingSettings,
)
from xianyu_automation.models import ReplyRequest, ReplyStatus
from xianyu_automation.store import StateStore
from xianyu_automation.workflow import ReplyWorkflow


def _xml(*values: str, unread: int = 1) -> str:
    nodes = [
        (
            f'<node text="" content-desc="消息，未读消息数{unread}，未选中状态" '
            'class="android.view.View" clickable="true" bounds="[0,0][1,1]" />'
        )
    ]
    nodes.extend(
        f'<node text="" content-desc="{value}" class="android.view.View" '
        'clickable="true" bounds="[10,10][20,20]" />'
        for value in values
    )
    return f"<hierarchy>{''.join(nodes)}</hierarchy>"


class FakeDevice:
    def __init__(self, *, marker_count: int = 1, confirm_send: bool = True):
        self.list_xml = _xml(unread=7)
        self.chat_values = ["AUTO_E2E_001"] * marker_count
        self.confirm_send = confirm_send
        self.prepared: list[str] = []
        self.sent_clicks = 0
        self.opened_y: int | None = None

    def navigate_to_messages(self) -> str:
        return self.list_xml

    def open_conversation(self, row_y: int) -> None:
        self.opened_y = row_y

    def ensure_chat(self) -> None:
        return None

    def dump_hierarchy(self) -> str:
        return _xml(*self.chat_values)

    def prepare_reply(self, reply: str, draft_screenshot: Path | None = None) -> None:
        self.prepared.append(reply)

    def send_once(self) -> None:
        self.sent_clicks += 1

    def wait_for_text(self, text: str) -> int:
        if not self.confirm_send:
            return 0
        self.chat_values.append(text)
        return 1

    def screenshot(self, path: Path) -> None:
        return None

    def return_to_messages(self) -> str:
        return _xml(unread=6)


def _config(tmp_path) -> AutomationConfig:
    return AutomationConfig(
        serial="device",
        adb_path="adb",
        state_file=tmp_path / "state.json",
        artifact_dir=tmp_path / "artifacts",
        app=AppSettings("com.taobao.idlefish", ".MainActivity", ".ChatActivity"),
        coordinates=CoordinateSettings(
            message_tab=(0.7, 0.9),
            conversation_x=0.5,
            input=(0.5, 0.9),
            candidate_commit=(0.4, 0.6),
            send=(0.9, 0.5),
        ),
        timings=TimingSettings(0, 0, 0, 1, 0),
        notifications=NotificationSettings(
            state_file=tmp_path / "notification-state.json",
            event_log=tmp_path / "notifications.jsonl",
            poll_seconds=1,
            message_channel_ids=("message-channel",),
        ),
        inbound=InboundSettings(
            notification_state_file=tmp_path / "inbound-notification-state.json",
            queue_state_file=tmp_path / "inbound-queue-state.json",
            queue_file=tmp_path / "inbound-pending.jsonl",
        ),
        delete_key_count=0,
    )


def test_dry_run_never_types_or_sends(tmp_path) -> None:
    config = _config(tmp_path)
    device = FakeDevice()
    workflow = ReplyWorkflow(config, device, StateStore(config.state_file))

    result = workflow.run(
        ReplyRequest(
            marker="AUTO_E2E_001",
            reply="收到，这是自动化联调测试。",
            conversation_y=925,
        )
    )

    assert result.status == ReplyStatus.DRY_RUN_READY
    assert device.prepared == []
    assert device.sent_clicks == 0


def test_apply_sends_once_and_records_duplicate_guard(tmp_path) -> None:
    config = _config(tmp_path)
    device = FakeDevice()
    workflow = ReplyWorkflow(config, device, StateStore(config.state_file))
    request = ReplyRequest(
        marker="AUTO_E2E_001",
        reply="收到，这是自动化联调测试。",
        conversation_y=925,
        apply=True,
    )

    first = workflow.run(request)
    second = workflow.run(request)

    assert first.status == ReplyStatus.SENT
    assert first.sent_clicks == 1
    assert first.unread_before == 7
    assert first.unread_after == 6
    assert second.status == ReplyStatus.SKIPPED_DUPLICATE
    assert device.sent_clicks == 1


def test_non_unique_marker_is_refused(tmp_path) -> None:
    config = _config(tmp_path)
    device = FakeDevice(marker_count=2)
    result = ReplyWorkflow(config, device, StateStore(config.state_file)).run(
        ReplyRequest(
            marker="AUTO_E2E_001",
            reply="reply",
            conversation_y=925,
            apply=True,
        )
    )

    assert result.status == ReplyStatus.TARGET_NOT_UNIQUE
    assert device.sent_clicks == 0


def test_unconfirmed_send_is_never_retried(tmp_path) -> None:
    config = _config(tmp_path)
    device = FakeDevice(confirm_send=False)
    result = ReplyWorkflow(config, device, StateStore(config.state_file)).run(
        ReplyRequest(
            marker="AUTO_E2E_001",
            reply="reply",
            conversation_y=925,
            apply=True,
        )
    )

    assert result.status == ReplyStatus.SEND_UNCONFIRMED
    assert result.sent_clicks == 1
    assert device.sent_clicks == 1
    assert not config.state_file.exists()
