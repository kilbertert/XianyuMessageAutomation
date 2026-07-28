import json

from xianyu_automation.models import NotificationEvent
from xianyu_automation.monitor import (
    JsonlEventSink,
    NotificationMonitor,
    NotificationStateStore,
)


def _event(
    fingerprint: str,
    text: str,
    *,
    message_candidate: bool = True,
) -> NotificationEvent:
    return NotificationEvent(
        fingerprint=fingerprint,
        source_key_sha256="source-hash",
        package="com.taobao.idlefish",
        channel="chat_message",
        category="msg",
        update_time_ms=1,
        observed_at="2026-07-28T00:00:00+00:00",
        title="测试买家",
        text=text,
        big_text=text,
        message_candidate=message_candidate,
    )


class FakeSource:
    def __init__(self, snapshots: list[list[NotificationEvent]]):
        self.snapshots = iter(snapshots)

    def snapshot(self) -> list[NotificationEvent]:
        return next(self.snapshots)


def test_monitor_baselines_existing_then_emits_only_new_event(tmp_path) -> None:
    old = _event("old-fingerprint", "old")
    new = _event("new-fingerprint", "new")
    state_path = tmp_path / "state.json"
    event_log = tmp_path / "events.jsonl"
    monitor = NotificationMonitor(
        FakeSource([[old], [old, new], [old, new]]),
        NotificationStateStore(state_path),
        JsonlEventSink(event_log),
    )

    assert monitor.poll(emit_existing=False) == []
    assert monitor.poll() == [new]
    assert monitor.poll() == []

    state_raw = state_path.read_text(encoding="utf-8")
    assert "old-fingerprint" in state_raw
    assert '"old"' not in state_raw
    lines = event_log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["text"] == "new"


def test_monitor_filters_non_message_notifications_by_default(tmp_path) -> None:
    marketing = _event("marketing", "promotion", message_candidate=False)
    monitor = NotificationMonitor(
        FakeSource([[marketing]]),
        NotificationStateStore(tmp_path / "state.json"),
        JsonlEventSink(tmp_path / "events.jsonl"),
    )

    assert monitor.poll() == []
    assert not (tmp_path / "events.jsonl").exists()
