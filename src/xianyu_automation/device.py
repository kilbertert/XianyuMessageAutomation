from __future__ import annotations

import subprocess
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

    def open_notification(self, title: str) -> str: ...

    def display_size(self) -> tuple[int, int]: ...

    def return_home(self) -> None: ...


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
        self._reply_prepared = False

    def _size(self) -> tuple[int, int]:
        info = self._device.info
        return int(info["displayWidth"]), int(info["displayHeight"])

    def display_size(self) -> tuple[int, int]:
        return self._size()

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
        if not self._device.is_input_ime_installed():
            raise DeviceStateError(
                "AdbKeyboard is not installed; complete the attended device setup"
            )
        self._reply_prepared = False
        self._click_ratio(self.config.coordinates.input)
        time.sleep(self.config.timings.input_seconds)

        previous_ime = self._device.current_ime()
        try:
            # The system IME can retain ASCII text as an uncommitted candidate.
            # AdbKeyboard writes directly into Flutter's editable field.
            self._device.set_input_ime(True)
            self._device.clear_text()
            for _ in range(self.config.delete_key_count):
                self._device.press("delete")

            self._device.send_keys(reply, clear=False)
            time.sleep(self.config.timings.input_seconds)
        finally:
            if previous_ime:
                self._device.shell(["ime", "enable", previous_ime])
                self._device.shell(["ime", "set", previous_ime])
                self._device.shell(
                    ["settings", "put", "secure", "default_input_method", previous_ime]
                )
                if self._device.current_ime() != previous_ime:
                    raise DeviceStateError("could not restore the previous input method")
        self._reply_prepared = True
        if draft_screenshot is not None:
            self.screenshot(draft_screenshot)

    def send_once(self) -> None:
        if not self._reply_prepared:
            raise DeviceStateError("reply was not prepared")
        self.ensure_chat()
        self._reply_prepared = False
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

    def reopen_chat(self, title: str) -> str:
        if not title:
            raise DeviceStateError("chat title must not be empty")
        self.ensure_chat()
        self._device.press("back")
        time.sleep(self.config.timings.page_seconds)

        selector = self._device(text=title)
        count = int(selector.count)
        if count == 0:
            selector = self._device(description=title)
            count = int(selector.count)
        if count != 1:
            raise DeviceStateError(
                f"chat title is not unique after send: {title!r} matched {count}"
            )

        selector.click()
        deadline = time.monotonic() + self.config.timings.page_seconds + 5
        while time.monotonic() < deadline:
            if self._current_activity() == self.config.app.chat_activity:
                time.sleep(1)
                return self.dump_hierarchy()
            time.sleep(self.config.timings.poll_seconds)
        raise DeviceStateError(
            "chat did not reopen after send; "
            f"current activity is {self._current_activity()}"
        )

    def open_notification(self, title: str) -> str:
        if not title:
            raise DeviceStateError("notification title must not be empty")
        self._device.open_notification()
        deadline = time.monotonic() + self.config.timings.page_seconds + 5
        selector = self._device(text=title)
        count = 0
        while time.monotonic() < deadline:
            selector = self._device(text=title)
            count = int(selector.count)
            if count == 0:
                selector = self._device(description=title)
                count = int(selector.count)
            if count != 0:
                break
            time.sleep(self.config.timings.poll_seconds)
        if count != 1:
            self._device.press("back")
            raise DeviceStateError(
                f"notification title is not unique: {title!r} matched {count}"
            )

        selector.click()
        deadline = time.monotonic() + self.config.timings.page_seconds + 5
        while time.monotonic() < deadline:
            if self._current_activity() == self.config.app.chat_activity:
                time.sleep(1)
                return self.dump_hierarchy()
            time.sleep(self.config.timings.poll_seconds)
        raise DeviceStateError(
            "notification did not open a chat; "
            f"current activity is {self._current_activity()}"
        )

    def return_home(self) -> None:
        self._device.press("home")
        time.sleep(1)
        process = subprocess.run(
            [
                self.config.adb_path,
                "-s",
                self.config.serial,
                "shell",
                "dumpsys",
                "window",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if process.returncode != 0:
            detail = process.stderr.strip() or "unknown adb error"
            raise DeviceStateError(f"cannot verify foreground window: {detail}")
        focus = "\n".join(
            line
            for line in process.stdout.splitlines()
            if "mCurrentFocus=" in line or "mFocusedApp=" in line
        )
        if not focus:
            raise DeviceStateError("cannot verify foreground window after Home")
        if self.config.app.package in focus:
            raise DeviceStateError("Xianyu remained in the foreground after Home")
