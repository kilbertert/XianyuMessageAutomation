from xianyu_automation.notifications import parse_notification_dump


XIAN_YU_RECORD = """
    NotificationRecord(0x1234: pkg=com.taobao.idlefish user=UserHandle{0}
      id=42 tag=null importance=4 key=0|com.taobao.idlefish|42|null|10001
      bbbc=0: Notification(channel=chat_message shortcut=null category=msg))
        extras={
          android.title=String (测试买家)
          android.text=String (AUTO_NOTIFY_001)
          android.bigText=String (AUTO_NOTIFY_001)
          android.template=String (android.app.Notification$MessagingStyle)
        }
        mCreationTimeMs=1000
        mUpdateTimeMs=2000
"""


def test_parse_xianyu_notification_without_exposing_source_key() -> None:
    dump = (
        XIAN_YU_RECORD
        + """
    NotificationRecord(0x5678: pkg=com.android.mms user=UserHandle{0}
      id=9 tag=null importance=4 key=other
      bbbc=0: Notification(channel=sms category=msg))
        mUpdateTimeMs=3000
"""
    )

    events = parse_notification_dump(
        dump,
        "com.taobao.idlefish",
        observed_at="2026-07-28T00:00:00+00:00",
    )

    assert len(events) == 1
    event = events[0]
    assert event.title == "测试买家"
    assert event.text == "AUTO_NOTIFY_001"
    assert event.channel == "chat_message"
    assert event.category == "msg"
    assert event.update_time_ms == 2000
    assert event.message_candidate is True
    assert "com.taobao.idlefish|42" not in event.source_key_sha256


def test_notification_update_changes_fingerprint() -> None:
    first = parse_notification_dump(XIAN_YU_RECORD, "com.taobao.idlefish")[0]
    second = parse_notification_dump(
        XIAN_YU_RECORD.replace("mUpdateTimeMs=2000", "mUpdateTimeMs=2001"),
        "com.taobao.idlefish",
    )[0]

    assert first.fingerprint != second.fingerprint


def test_configured_channel_marks_message_without_category() -> None:
    dump = XIAN_YU_RECORD.replace("category=msg", "category=null").replace(
        "chat_message", "mipush|com.taobao.idlefish|107787"
    )

    event = parse_notification_dump(
        dump,
        "com.taobao.idlefish",
        message_channel_ids=("mipush|com.taobao.idlefish|107787",),
    )[0]

    assert event.message_candidate is True
