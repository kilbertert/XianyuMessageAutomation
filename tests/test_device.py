from types import SimpleNamespace

from xianyu_automation.device import Uiautomator2Device


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
