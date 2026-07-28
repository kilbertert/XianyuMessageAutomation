from __future__ import annotations

import re
import shutil
import subprocess
from typing import Any

from .config import AutomationConfig


class AdbDoctor:
    def __init__(self, config: AutomationConfig):
        self.config = config

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [self.config.adb_path, "-s", self.config.serial, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )

    def inspect(self) -> dict[str, Any]:
        adb_resolved = shutil.which(self.config.adb_path)
        if not adb_resolved:
            return {"ok": False, "error": f"adb not found: {self.config.adb_path}"}

        devices = subprocess.run(
            [self.config.adb_path, "devices"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        connected = any(
            line.split(maxsplit=1)[0] == self.config.serial
            and len(line.split(maxsplit=1)) == 2
            and line.split(maxsplit=1)[1] == "device"
            for line in devices.stdout.splitlines()
            if line.strip()
        )
        if not connected:
            return {
                "ok": False,
                "adb": adb_resolved,
                "serial": self.config.serial,
                "error": "device is not connected in adb device state",
            }

        input_check = self._run("shell", "input", "keyevent", "0")
        package = self._run("shell", "dumpsys", "package", self.config.app.package)
        version_name = re.search(r"versionName=(\S+)", package.stdout)
        version_code = re.search(r"versionCode=(\d+)", package.stdout)

        return {
            "ok": input_check.returncode == 0 and package.returncode == 0,
            "adb": adb_resolved,
            "serial": self.config.serial,
            "input_injection": input_check.returncode == 0,
            "package": self.config.app.package,
            "version_name": version_name.group(1) if version_name else None,
            "version_code": int(version_code.group(1)) if version_code else None,
            "input_error": input_check.stderr.strip() or None,
        }
