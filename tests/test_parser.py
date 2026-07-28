from xianyu_automation.parser import find_text, parse_bounds, unread_count


def test_parse_bounds() -> None:
    assert parse_bounds("[179,684][525,794]").right == 525
    assert parse_bounds("invalid") is None


def test_unread_count_and_marker_are_parsed() -> None:
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <hierarchy>
      <node text="" content-desc="消息，未读消息数7，未选中状态"
            class="android.widget.FrameLayout" clickable="true" bounds="[0,0][1,1]" />
      <node text="" content-desc="AUTO_E2E_001"
            class="android.view.View" clickable="true" bounds="[179,684][525,794]" />
    </hierarchy>"""

    assert unread_count(xml) == 7
    matches = find_text(xml, "auto_e2e_001")
    assert len(matches) == 1
    assert matches[0].bounds.left == 179


def test_find_text_can_be_case_sensitive() -> None:
    xml = """<hierarchy>
      <node text="" content-desc="Hello" class="android.view.View"
            clickable="false" bounds="[0,0][1,1]" />
    </hierarchy>"""
    assert len(find_text(xml, "hello")) == 1
    assert find_text(xml, "hello", case_sensitive=True) == []


def test_unread_count_is_zero_when_message_tab_has_no_unread() -> None:
    xml = """<hierarchy>
      <node text="" content-desc="消息，无未读消息，选中状态"
            class="android.view.View" clickable="true" bounds="[0,0][1,1]" />
    </hierarchy>"""

    assert unread_count(xml) == 0
