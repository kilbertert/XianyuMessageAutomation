from pathlib import Path

import pytest

from xianyu_automation.config import (
    AppSettings,
    AutomationConfig,
    CoordinateSettings,
    GatewaySettings,
    InboundSettings,
    NotificationSettings,
    TimingSettings,
)
from xianyu_automation.errors import AutomationError
from xianyu_automation.gateway import GatewayDeliveryStore, GatewayWorkflow
from xianyu_automation.models import GatewayStatus, NotificationEvent


CHAT_XML = """<hierarchy>
  <node text="" content-desc="买家甲" class="android.view.View"
        clickable="true" bounds="[350,80][700,180]" />
  <node text="" content-desc="请问还在吗" class="android.view.View"
        clickable="true" bounds="[179,1201][531,1311]" />
  <node text="" content-desc="请输入消息" class="android.widget.EditText"
        clickable="true" bounds="[100,2110][850,2240]" />
</hierarchy>"""


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
            consumer_state_file=tmp_path / "inbound-consumer-state.json",
        ),
        delete_key_count=0,
        gateway=GatewaySettings(
            base_url="http://100.96.121.55:9090",
            account_id="account-001",
            device_id="android-primary",
            shared_secret_env="ANDROID_GATEWAY_SHARED_SECRET",
            state_file=tmp_path / "gateway-state.json",
            notification_state_file=tmp_path / "gateway-notification-state.json",
            request_timeout_seconds=3,
            max_attempts=2,
        ),
    )


def _notification() -> NotificationEvent:
    return NotificationEvent(
        fingerprint="notification-001",
        source_key_sha256="source-key",
        package="com.taobao.idlefish",
        channel="message-channel",
        category=None,
        update_time_ms=1785227256417,
        observed_at="2026-07-28T08:28:38+00:00",
        title="买家甲",
        text="发来一条新消息",
        big_text=None,
        message_candidate=True,
    )


class FakeDevice:
    def __init__(self) -> None:
        self.chat_xml = CHAT_XML
        self.prepared = []
        self.sent_clicks = 0
        self.home_count = 0
        self.chat_checks = 0

    def open_notification(self, title: str) -> str:
        assert title == "买家甲"
        return self.chat_xml

    def display_size(self) -> tuple[int, int]:
        return 1080, 2400

    def ensure_chat(self) -> None:
        self.chat_checks += 1

    def dump_hierarchy(self) -> str:
        return self.chat_xml

    def prepare_reply(self, reply: str, draft_screenshot: Path | None = None) -> None:
        self.prepared.append(reply)

    def send_once(self) -> None:
        self.sent_clicks += 1
        self.chat_xml = self.chat_xml.replace(
            "</hierarchy>",
            '<node text="" content-desc="在的" class="android.view.View" '
            'clickable="true" bounds="[600,1400][950,1500]" /></hierarchy>',
        )

    def return_home(self) -> None:
        self.home_count += 1


class FakeClient:
    def __init__(self, *, action: str = "reply", fail_submit: bool = False):
        self.action = action
        self.fail_submit = fail_submit
        self.submitted = []
        self.receipts = []

    def health(self) -> dict:
        return {"ok": True, "enabled": True}

    def submit(self, payload: dict) -> dict:
        self.submitted.append(payload)
        if self.fail_submit:
            raise AutomationError("server unavailable")
        return {
            "event_id": payload["event_id"],
            "duplicate": False,
            "correlation_status": "matched",
            "decision": {
                "action": self.action,
                "text": "在的" if self.action == "reply" else None,
                "source": "关键词" if self.action == "reply" else None,
                "reason": "matched" if self.action == "reply" else "no_reply_rule",
            },
        }

    def receipt(self, event_id: str, outcome: str) -> dict:
        self.receipts.append((event_id, outcome))
        return {"event_id": event_id, "outcome": outcome, "changed": True}


def test_gateway_sends_server_decision_once_and_receipts_success(tmp_path) -> None:
    config = _config(tmp_path)
    device = FakeDevice()
    client = FakeClient()
    store = GatewayDeliveryStore(config.gateway.state_file)
    workflow = GatewayWorkflow(config, device, client, store)

    result = workflow.process(_notification())

    assert result.status == GatewayStatus.SENT
    assert device.prepared == ["在的"]
    assert device.sent_clicks == 1
    assert device.home_count == 1
    assert client.receipts == [(result.event_id, "sent")]
    assert store.pending() is None


def test_gateway_noop_never_touches_input_and_receipts_skip(tmp_path) -> None:
    config = _config(tmp_path)
    device = FakeDevice()
    client = FakeClient(action="noop")
    workflow = GatewayWorkflow(
        config,
        device,
        client,
        GatewayDeliveryStore(config.gateway.state_file),
    )

    result = workflow.process(_notification())

    assert result.status == GatewayStatus.NO_REPLY
    assert device.prepared == []
    assert device.sent_clicks == 0
    assert device.home_count == 1
    assert client.receipts == [(result.event_id, "skipped")]


def test_gateway_server_failure_keeps_chat_open_for_resume(tmp_path) -> None:
    config = _config(tmp_path)
    device = FakeDevice()
    workflow = GatewayWorkflow(
        config,
        device,
        FakeClient(fail_submit=True),
        GatewayDeliveryStore(config.gateway.state_file),
    )

    with pytest.raises(AutomationError, match="unavailable"):
        workflow.process(_notification())

    assert device.home_count == 0
    assert workflow.store.pending()["phase"] == "extracted"


def test_gateway_resume_never_reclicks_an_uncertain_send(tmp_path) -> None:
    config = _config(tmp_path)
    device = FakeDevice()
    client = FakeClient()
    store = GatewayDeliveryStore(config.gateway.state_file)
    event = {
        "event_id": "event-uncertain",
        "device_id": "android-primary",
        "account_id": "account-001",
        "notification_id": "notification-001",
        "sender_label": "买家甲",
        "body": "请问还在吗",
        "observed_at": "2026-07-28T08:28:38+00:00",
    }
    store.begin(event)
    store.set_decision(
        event["event_id"],
        {
            "action": "reply",
            "text": "在的",
            "source": "关键词",
            "reason": "matched",
        },
    )
    store.set_phase(event["event_id"], "sending")
    workflow = GatewayWorkflow(config, device, client, store)

    result = workflow.resume()

    assert result.status == GatewayStatus.SEND_UNCONFIRMED
    assert device.sent_clicks == 0
    assert client.receipts == [("event-uncertain", "send_unconfirmed")]
    assert device.home_count == 1
