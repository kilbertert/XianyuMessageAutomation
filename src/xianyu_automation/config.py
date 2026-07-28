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
class NotificationSettings:
    state_file: Path
    event_log: Path
    poll_seconds: float
    message_channel_ids: tuple[str, ...]


@dataclass(frozen=True)
class InboundSettings:
    notification_state_file: Path
    queue_state_file: Path
    queue_file: Path
    consumer_state_file: Path


@dataclass(frozen=True)
class GatewaySettings:
    base_url: str
    account_id: str
    device_id: str
    shared_secret_env: str
    state_file: Path
    notification_state_file: Path
    request_timeout_seconds: float
    max_attempts: int


@dataclass(frozen=True)
class AutomationConfig:
    serial: str
    adb_path: str
    state_file: Path
    artifact_dir: Path
    app: AppSettings
    coordinates: CoordinateSettings
    timings: TimingSettings
    notifications: NotificationSettings
    inbound: InboundSettings
    delete_key_count: int
    gateway: GatewaySettings | None = None


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
        notifications_raw = raw.get("notifications", {})
        inbound_raw = raw.get("inbound", {})
        gateway_raw = raw.get("gateway")
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
        notification_poll_seconds = float(notifications_raw.get("poll_seconds", 1.0))
        if notification_poll_seconds <= 0:
            raise ConfigurationError("notifications.poll_seconds must be positive")
        message_channels_raw = notifications_raw.get("message_channel_ids", [])
        if not isinstance(message_channels_raw, list):
            raise ConfigurationError(
                "notifications.message_channel_ids must be a JSON array"
            )

        gateway = None
        if gateway_raw is not None:
            if not isinstance(gateway_raw, dict):
                raise ConfigurationError("gateway must be a JSON object")
            request_timeout_seconds = float(
                gateway_raw.get("request_timeout_seconds", 30)
            )
            max_attempts = int(gateway_raw.get("max_attempts", 3))
            if request_timeout_seconds <= 0:
                raise ConfigurationError(
                    "gateway.request_timeout_seconds must be positive"
                )
            if max_attempts <= 0:
                raise ConfigurationError("gateway.max_attempts must be positive")
            base_url = str(gateway_raw["base_url"]).strip().rstrip("/")
            account_id = str(gateway_raw["account_id"]).strip()
            device_id = str(gateway_raw["device_id"]).strip()
            shared_secret_env = str(
                gateway_raw.get(
                    "shared_secret_env",
                    "ANDROID_GATEWAY_SHARED_SECRET",
                )
            ).strip()
            if not all((base_url, account_id, device_id, shared_secret_env)):
                raise ConfigurationError(
                    "gateway base_url, account_id, device_id and shared_secret_env "
                    "must not be empty"
                )
            gateway = GatewaySettings(
                base_url=base_url,
                account_id=account_id,
                device_id=device_id,
                shared_secret_env=shared_secret_env,
                state_file=(
                    base / gateway_raw.get("state_file", "var/gateway-state.json")
                ).resolve(),
                notification_state_file=(
                    base
                    / gateway_raw.get(
                        "notification_state_file",
                        "var/gateway-notification-state.json",
                    )
                ).resolve(),
                request_timeout_seconds=request_timeout_seconds,
                max_attempts=max_attempts,
            )

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
            notifications=NotificationSettings(
                state_file=(
                    base
                    / notifications_raw.get(
                        "state_file", "var/notification-state.json"
                    )
                ).resolve(),
                event_log=(
                    base
                    / notifications_raw.get(
                        "event_log", "var/inbound-notifications.jsonl"
                    )
                ).resolve(),
                poll_seconds=notification_poll_seconds,
                message_channel_ids=tuple(
                    str(channel).strip()
                    for channel in message_channels_raw
                    if str(channel).strip()
                ),
            ),
            inbound=InboundSettings(
                notification_state_file=(
                    base
                    / inbound_raw.get(
                        "notification_state_file",
                        "var/inbound-notification-state.json",
                    )
                ).resolve(),
                queue_state_file=(
                    base
                    / inbound_raw.get(
                        "queue_state_file",
                        "var/inbound-queue-state.json",
                    )
                ).resolve(),
                queue_file=(
                    base
                    / inbound_raw.get(
                        "queue_file",
                        "var/inbound-pending.jsonl",
                    )
                ).resolve(),
                consumer_state_file=(
                    base
                    / inbound_raw.get(
                        "consumer_state_file",
                        "var/inbound-consumer-state.json",
                    )
                ).resolve(),
            ),
            delete_key_count=delete_key_count,
            gateway=gateway,
        )
    except KeyError as exc:
        raise ConfigurationError(f"missing configuration field: {exc}") from exc
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"invalid configuration value: {exc}") from exc
