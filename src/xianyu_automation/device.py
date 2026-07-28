from __future__ import annotations

import time
from pathlib import Path
from typing import Protocol

from .config import AutomationConfig
from .errors import DeviceStateError
from .parser import find_text, unread_count


class DevicePort(Protocol):
    def navigate_to_messages(self) -> str: ...

    def open_conversation(self, row_y: int) -> None: ...

    def ensure_chat(self) -> None: ...

    def dump_hierarchy(self) -> str: ...

    def prepare_reply(self, reply: str, draft_screenshot: Path | None = None) -> None: ...

    def send_once(self) -> None: ...

    def wait_for_text(self, text: str) -> int: ...

    def screenshot(self, path: Path) -> None: ...

    def return_to_messages(self) -> str: ...


class Uiautomator2Device:
    def __init__(self, config: AutomationConfig):
        try:
            import uiautomator2 as u2
        except ImportError as exc:
            raise DeviceStateError(
                "uiautomator2 is not installed; run pip install -e ."
            ) from exc

        self.config = config
        self._device = u2.connect(config.serial)
        self.sent_clicks = 0

    def _size(self) -> tuple[int, int]:
        info = self._device.info
        return int(info["displayWidth"]), int(info["displayHeight"])

    def _click_ratio(self, point: tuple[float, float]) -> None:
        width, height = self._size()
        self._device.click(int(width * point[0]), int(height * point[1]))

    def _current_activity(self) -> str:
        return str(self._device.app_current().get("activity", ""))

    def _leave_chat(self) -> None:
        for _ in range(2):
            if self._current_activity() != self.config.app.chat_activity:
                return
            self._device.press("back")
            time.sleep(1)
        if self._current_activity() == self.config.app.chat_activity:
            raise DeviceStateError("could not leave the current chat")

    def navigate_to_messages(self) -> str:
        self._device.app_start(self.config.app.package, stop=False)
        time.sleep(self.config.timings.app_start_seconds)
        self._leave_chat()
        clicked = self._device(text="消息").click_exists(timeout=3)
        if not clicked:
            self._click_ratio(self.config.coordinates.message_tab)
        time.sleep(self.config.timings.page_seconds)
        xml = self.dump_hierarchy()
        if unread_count(xml) is None:
            raise DeviceStateError("message page was not detected after navigation")
        return xml

    def open_conversation(self, row_y: int) -> None:
        width, height = self._size()
        if not 0 < row_y < height:
            raise DeviceStateError(f"conversation row y is outside the screen: {row_y}")
        self._device.click(int(width * self.config.coordinates.conversation_x), row_y)
        deadline = time.monotonic() + self.config.timings.page_seconds + 5
        while time.monotonic() < deadline:
            if self._current_activity() == self.config.app.chat_activity:
                time.sleep(1)
                return
            time.sleep(self.config.timings.poll_seconds)
        raise DeviceStateError(
            f"chat activity did not open; current activity is {self._current_activity()}"
        )

    def ensure_chat(self) -> None:
        if self._current_activity() != self.config.app.chat_activity:
            raise DeviceStateError(
                f"expected chat activity, current activity is {self._current_activity()}"
            )

    def dump_hierarchy(self) -> str:
        return self._device.dump_hierarchy(compressed=False)

    def prepare_reply(self, reply: str, draft_screenshot: Path | None = None) -> None:
        if not reply:
            raise DeviceStateError("reply must not be empty")
        self._click_ratio(self.config.coordinates.input)
        time.sleep(self.config.timings.input_seconds)

        # Flutter's editable text may retain an invisible composition. Clear it
        # defensively before injecting the requested reply.
        self._device.clear_text()
        for _ in range(self.config.delete_key_count):
            self._device.press("delete")

        self._device.send_keys(reply, clear=False)
        time.sleep(self.config.timings.input_seconds)
        if not reply.isascii():
            self._click_ratio(self.config.coordinates.candidate_commit)
            time.sleep(self.config.timings.input_seconds)
        if draft_screenshot is not None:
            self.screenshot(draft_screenshot)

    def send_once(self) -> None:
        self._click_ratio(self.config.coordinates.send)
        self.sent_clicks += 1

    def wait_for_text(self, text: str) -> int:
        deadline = time.monotonic() + self.config.timings.send_timeout_seconds
        while time.monotonic() < deadline:
            count = len(find_text(self.dump_hierarchy(), text))
            if count:
                return count
            time.sleep(self.config.timings.poll_seconds)
        return 0

    def screenshot(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._device.screenshot(str(path))

    def return_to_messages(self) -> str:
        return self.navigate_to_messages()
