from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import ConfigurationError


@dataclass(frozen=True)
class AppSettings:
    package: str
    main_activity: str
    chat_activity: str


@dataclass(frozen=True)
class CoordinateSettings:
    message_tab: tuple[float, float]
    conversation_x: float
    input: tuple[float, float]
    candidate_commit: tuple[float, float]
    send: tuple[float, float]


@dataclass(frozen=True)
class TimingSettings:
    app_start_seconds: float
    page_seconds: float
    input_seconds: float
    send_timeout_seconds: float
    poll_seconds: float


@dataclass(frozen=True)
class AutomationConfig:
    serial: str
    adb_path: str
    state_file: Path
    artifact_dir: Path
    app: AppSettings
    coordinates: CoordinateSettings
    timings: TimingSettings
    delete_key_count: int


def _point(value: Any, name: str) -> tuple[float, float]:
    if not isinstance(value, list) or len(value) != 2:
        raise ConfigurationError(f"{name} must be a two-item JSON array")
    point = (float(value[0]), float(value[1]))
    if not all(0.0 <= item <= 1.0 for item in point):
        raise ConfigurationError(f"{name} values must be between 0 and 1")
    return point


def load_config(path: str | Path) -> AutomationConfig:
    config_path = Path(path).resolve()
    if not config_path.is_file():
        raise ConfigurationError(
            f"configuration file not found: {config_path}; copy config.example.json to config.json"
        )

    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"cannot read configuration: {exc}") from exc

    try:
        app_raw = raw["app"]
        coordinates_raw = raw["coordinates"]
        timings_raw = raw["timings"]
        base = config_path.parent

        serial = str(raw["serial"]).strip()
        if not serial:
            raise ConfigurationError("serial must not be empty")

        conversation_x = float(coordinates_raw["conversation_x"])
        if not 0.0 <= conversation_x <= 1.0:
            raise ConfigurationError("coordinates.conversation_x must be between 0 and 1")

        delete_key_count = int(raw.get("delete_key_count", 80))
        if delete_key_count < 0:
            raise ConfigurationError("delete_key_count must be non-negative")

        return AutomationConfig(
            serial=serial,
            adb_path=str(raw.get("adb_path", "adb")),
            state_file=(base / raw.get("state_file", "var/state.json")).resolve(),
            artifact_dir=(base / raw.get("artifact_dir", "var/artifacts")).resolve(),
            app=AppSettings(
                package=str(app_raw["package"]),
                main_activity=str(app_raw["main_activity"]),
                chat_activity=str(app_raw["chat_activity"]),
            ),
            coordinates=CoordinateSettings(
                message_tab=_point(coordinates_raw["message_tab"], "coordinates.message_tab"),
                conversation_x=conversation_x,
                input=_point(coordinates_raw["input"], "coordinates.input"),
                candidate_commit=_point(
                    coordinates_raw["candidate_commit"], "coordinates.candidate_commit"
                ),
                send=_point(coordinates_raw["send"], "coordinates.send"),
            ),
            timings=TimingSettings(
                app_start_seconds=float(timings_raw["app_start_seconds"]),
                page_seconds=float(timings_raw["page_seconds"]),
                input_seconds=float(timings_raw["input_seconds"]),
                send_timeout_seconds=float(timings_raw["send_timeout_seconds"]),
                poll_seconds=float(timings_raw["poll_seconds"]),
            ),
            delete_key_count=delete_key_count,
        )
    except KeyError as exc:
        raise ConfigurationError(f"missing configuration field: {exc}") from exc
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"invalid configuration value: {exc}") from exc
