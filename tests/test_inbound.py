import json

import pytest

from xianyu_automation.errors import DeviceStateError
from xianyu_automation.inbound import (
    InboundPoller,
    InboundQueue,
    InboundWorkflow,
    incoming_chat_messages,
)
from xianyu_automation.models import NotificationEvent
from xianyu_automation.monitor import NotificationStateStore


CHAT_XML = """<hierarchy>
  <node text="" content-desc="x***3" class="android.view.View"
        clickable="true" bounds="[350,80][700,180]" />
  <node text="" content-desc="auto_e2e_001" class="android.view.View"
        clickable="true" bounds="[179,684][525,794]" />
  <node text="" content-desc="收到，这是自动化联调测试。" class="android.view.View"
        clickable="true" bounds="[263,882][901,992]" />
  <node text="" content-desc="auto_e2e_002" class="android.view.View"
        clickable="true" bounds="[179,1201][531,1311]" />
  <node text="" content-desc="请输入消息" class="android.widget.EditText"
        clickable="true" bounds="[100,2110][850,2240]" />
</hierarchy>"""


def test_incoming_chat_messages_excludes_outgoing_and_controls() -> None:
    messages = incoming_chat_messages(CHAT_XML, width=1080, height=2400)

    assert [message.value for message in messages] == [
        "auto_e2e_001",
        "auto_e2e_002",
    ]


class FakeInboundDevice:
    def __init__(self) -> None:
        self.opened_titles: list[str] = []
        self.home_count = 0

    def open_notification(self, title: str) -> str:
        self.opened_titles.append(title)
        return CHAT_XML

    def display_size(self) -> tuple[int, int]:
        return 1080, 2400

    def return_home(self) -> None:
        self.home_count += 1


def _notification(fingerprint: str = "notification-fingerprint") -> NotificationEvent:
    return NotificationEvent(
        fingerprint=fingerprint,
        source_key_sha256="source-key-hash",
        package="com.taobao.idlefish",
        channel="mipush|com.taobao.idlefish|107787",
        category=None,
        update_time_ms=1785227256417,
        observed_at="2026-07-28T08:28:38+00:00",
        title="x***3",
        text="发来一条新消息",
        big_text=None,
        message_candidate=True,
    )


def test_inbound_workflow_routes_latest_message_to_queue_and_returns_home(tmp_path) -> None:
    device = FakeInboundDevice()
    queue_file = tmp_path / "pending.jsonl"
    workflow = InboundWorkflow(
        device,
        InboundQueue(tmp_path / "inbound-state.json", queue_file),
    )

    result = workflow.process(_notification())

    assert result.status == "queued"
    assert result.body == "auto_e2e_002"
    assert result.sent_clicks == 0
    assert device.opened_titles == ["x***3"]
    assert device.home_count == 1
    rows = [
        json.loads(line)
        for line in queue_file.read_text(encoding="utf-8").splitlines()
    ]
    assert [row["body"] for row in rows] == ["auto_e2e_002"]


def test_inbound_workflow_deduplicates_queue_without_plaintext_state(tmp_path) -> None:
    device = FakeInboundDevice()
    state_file = tmp_path / "inbound-state.json"
    queue_file = tmp_path / "pending.jsonl"
    workflow = InboundWorkflow(device, InboundQueue(state_file, queue_file))

    first = workflow.process(_notification())
    second = workflow.process(_notification())

    assert first.status == "queued"
    assert second.status == "skipped_duplicate"
    assert len(queue_file.read_text(encoding="utf-8").splitlines()) == 1
    state_raw = state_file.read_text(encoding="utf-8")
    assert "auto_e2e_002" not in state_raw
    assert "x***3" not in state_raw
    assert device.home_count == 2


class FakeNotificationSource:
    def __init__(self, snapshots: list[list[NotificationEvent]]):
        self.snapshots = iter(snapshots)

    def snapshot(self) -> list[NotificationEvent]:
        return next(self.snapshots)


def test_inbound_poller_baselines_old_notification_then_routes_new_one(tmp_path) -> None:
    old = _notification("old-notification")
    new = _notification("new-notification")
    device = FakeInboundDevice()
    workflow = InboundWorkflow(
        device,
        InboundQueue(tmp_path / "inbound-state.json", tmp_path / "pending.jsonl"),
    )
    poller = InboundPoller(
        FakeNotificationSource([[old], [old, new]]),
        NotificationStateStore(tmp_path / "notification-state.json"),
        workflow,
    )

    assert poller.poll(include_existing=False) == []
    results = poller.poll()

    assert [result.status for result in results] == ["queued"]
    assert device.opened_titles == ["x***3"]


class FailingOnceWorkflow:
    def __init__(self, workflow: InboundWorkflow):
        self.workflow = workflow
        self.calls = 0

    def process(self, event: NotificationEvent):
        self.calls += 1
        if self.calls == 1:
            raise DeviceStateError("transient route failure")
        return self.workflow.process(event)


def test_inbound_poller_acknowledges_only_after_success(tmp_path) -> None:
    event = _notification()
    device = FakeInboundDevice()
    workflow = FailingOnceWorkflow(
        InboundWorkflow(
            device,
            InboundQueue(
                tmp_path / "inbound-state.json",
                tmp_path / "pending.jsonl",
            ),
        )
    )
    poller = InboundPoller(
        FakeNotificationSource([[event], [event]]),
        NotificationStateStore(tmp_path / "notification-state.json"),
        workflow,
    )

    with pytest.raises(DeviceStateError, match="transient"):
        poller.poll()
    results = poller.poll()

    assert [result.status for result in results] == ["queued"]
    assert workflow.calls == 2
