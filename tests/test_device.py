from types import SimpleNamespace

import pytest

from xianyu_automation.device import Uiautomator2Device
from xianyu_automation.errors import DeviceStateError


class FakeU2Device:
    def __init__(self, activities: list[str]):
        self.activities = activities
        self.back_presses = 0

    def app_current(self) -> dict[str, str]:
        return {"activity": self.activities[min(self.back_presses, len(self.activities) - 1)]}

    def press(self, key: str) -> None:
        assert key == "back"
        self.back_presses += 1


def _device(activities: list[str]) -> tuple[Uiautomator2Device, FakeU2Device]:
    device = object.__new__(Uiautomator2Device)
    backing = FakeU2Device(activities)
    device.config = SimpleNamespace(app=SimpleNamespace(chat_activity=".ChatActivity"))
    device._device = backing
    return device, backing


def test_leave_chat_handles_open_keyboard_then_chat(monkeypatch) -> None:
    monkeypatch.setattr("xianyu_automation.device.time.sleep", lambda _: None)
    device, backing = _device([".ChatActivity", ".ChatActivity", ".MainActivity"])

    device._leave_chat()

    assert backing.back_presses == 2


def test_leave_chat_does_not_press_back_from_main_activity() -> None:
    device, backing = _device([".MainActivity"])

    device._leave_chat()

    assert backing.back_presses == 0


class FakeSelector:
    def __init__(self, count: int):
        self.count = count
        self.clicks = 0

    def click(self) -> None:
        self.clicks += 1


class FakeNotificationDevice:
    def __init__(self, title_count: int):
        self.title = FakeSelector(title_count)
        self.description = FakeSelector(0)
        self.notification_opens = 0
        self.back_presses = 0

    def open_notification(self) -> None:
        self.notification_opens += 1

    def __call__(self, **selector):
        return self.title if "text" in selector else self.description

    def press(self, key: str) -> None:
        assert key == "back"
        self.back_presses += 1


def test_open_notification_refuses_non_unique_sender_title(monkeypatch) -> None:
    monkeypatch.setattr("xianyu_automation.device.time.sleep", lambda _: None)
    device = object.__new__(Uiautomator2Device)
    backing = FakeNotificationDevice(title_count=2)
    device._device = backing
    device.config = SimpleNamespace(
        app=SimpleNamespace(chat_activity=".ChatActivity"),
        timings=SimpleNamespace(page_seconds=0, poll_seconds=0),
    )

    with pytest.raises(DeviceStateError, match="not unique"):
        device.open_notification("x***3")

    assert backing.notification_opens == 1
    assert backing.title.clicks == 0
    assert backing.back_presses == 1


class FakeReplyDevice:
    def __init__(self) -> None:
        self.ime = "com.example/.OriginalIme"
        self.original_ime = self.ime
        self.cleared = 0
        self.keys: list[str] = []
        self.sent: list[tuple[str, bool]] = []
        self.shell_calls: list[list[str]] = []

    def current_ime(self) -> str:
        return self.ime

    def is_input_ime_installed(self) -> bool:
        return True

    def set_input_ime(self, enabled: bool) -> None:
        assert enabled
        self.ime = "com.github.uiautomator/.AdbKeyboard"

    def clear_text(self) -> None:
        self.cleared += 1

    def press(self, key: str) -> None:
        self.keys.append(key)

    def send_keys(self, value: str, clear: bool) -> None:
        self.sent.append((value, clear))

    def shell(self, command: list[str]) -> None:
        self.shell_calls.append(command)
        if command[:2] == ["ime", "set"]:
            self.ime = command[2]


def test_prepare_reply_uses_adb_keyboard_and_restores_original_ime(monkeypatch) -> None:
    monkeypatch.setattr("xianyu_automation.device.time.sleep", lambda _: None)
    device = object.__new__(Uiautomator2Device)
    backing = FakeReplyDevice()
    clicks = []
    device._device = backing
    device._click_ratio = clicks.append
    device.config = SimpleNamespace(
        coordinates=SimpleNamespace(input=(0.5, 0.9)),
        timings=SimpleNamespace(input_seconds=0),
        delete_key_count=2,
    )

    device.prepare_reply("ASCII reply")

    assert clicks == [(0.5, 0.9)]
    assert backing.cleared == 1
    assert backing.keys == ["delete", "delete"]
    assert backing.sent == [("ASCII reply", False)]
    assert backing.current_ime() == backing.original_ime
    assert device._reply_prepared is True


def test_send_once_clicks_calibrated_button_after_preparation() -> None:
    device = object.__new__(Uiautomator2Device)
    clicks = []
    chat_checks = []
    device._click_ratio = clicks.append
    device.ensure_chat = lambda: chat_checks.append(True)
    device.config = SimpleNamespace(coordinates=SimpleNamespace(send=(0.9, 0.95)))
    device.sent_clicks = 0
    device._reply_prepared = True

    device.send_once()

    assert chat_checks == [True]
    assert clicks == [(0.9, 0.95)]
    assert device.sent_clicks == 1
    assert device._reply_prepared is False


def test_send_once_refuses_unprepared_reply() -> None:
    device = object.__new__(Uiautomator2Device)
    device.sent_clicks = 0
    device._reply_prepared = False

    with pytest.raises(DeviceStateError, match="not prepared"):
        device.send_once()

    assert device.sent_clicks == 0


def test_prepare_reply_requires_attended_adb_keyboard_setup() -> None:
    device = object.__new__(Uiautomator2Device)
    backing = FakeReplyDevice()
    backing.is_input_ime_installed = lambda: False
    device._device = backing

    with pytest.raises(DeviceStateError, match="attended device setup"):
        device.prepare_reply("ASCII reply")


class FakeHomeDevice:
    def __init__(self) -> None:
        self.pressed_keys: list[str] = []

    def press(self, key: str) -> None:
        self.pressed_keys.append(key)


def test_return_home_fails_when_system_focus_stays_in_xianyu(monkeypatch) -> None:
    monkeypatch.setattr("xianyu_automation.device.time.sleep", lambda _: None)
    monkeypatch.setattr(
        "xianyu_automation.device.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=(
                "mCurrentFocus=Window{abc u0 "
                "com.taobao.idlefish/.maincontainer.activity.MainActivity}"
            ),
            stderr="",
        ),
    )
    device = object.__new__(Uiautomator2Device)
    backing = FakeHomeDevice()
    device._device = backing
    device.config = SimpleNamespace(
        serial="device",
        adb_path="adb",
        app=SimpleNamespace(package="com.taobao.idlefish"),
    )

    with pytest.raises(DeviceStateError, match="foreground"):
        device.return_home()

    assert backing.pressed_keys == ["home"]
