from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import tempfile
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

from .config import AutomationConfig, GatewaySettings
from .errors import AutomationError, DeviceStateError
from .inbound import incoming_chat_messages
from .models import GatewayResult, GatewayStatus, NotificationEvent
from .parser import find_text


class GatewayClientPort(Protocol):
    def health(self) -> dict[str, Any]: ...

    def submit(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    def receipt(self, event_id: str, outcome: str) -> dict[str, Any]: ...


class GatewayDevicePort(Protocol):
    def open_notification(self, title: str) -> str: ...

    def display_size(self) -> tuple[int, int]: ...

    def ensure_chat(self) -> None: ...

    def dump_hierarchy(self) -> str: ...

    def prepare_reply(self, reply: str, draft_screenshot: Path | None = None) -> None: ...

    def send_once(self) -> None: ...

    def return_home(self) -> None: ...


def _signed_headers(secret: str, body: bytes, timestamp: int) -> dict[str, str]:
    message = str(timestamp).encode("ascii") + b"\n" + body
    signature = hmac.new(
        secret.encode("utf-8"),
        message,
        hashlib.sha256,
    ).hexdigest()
    return {
        "content-type": "application/json",
        "x-gateway-timestamp": str(timestamp),
        "x-gateway-signature": signature,
    }


def _validate_gateway_url(base_url: str) -> None:
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise AutomationError("gateway.base_url must be an absolute HTTP(S) URL")
    if parsed.scheme == "https":
        return
    if parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
        return
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError as exc:
        raise AutomationError(
            "plain HTTP gateway URLs are allowed only on loopback or Tailscale"
        ) from exc
    if address not in ipaddress.ip_network("100.64.0.0/10"):
        raise AutomationError(
            "plain HTTP gateway URLs are allowed only on loopback or Tailscale"
        )


class GatewayClient:
    def __init__(self, settings: GatewaySettings):
        _validate_gateway_url(settings.base_url)
        self.settings = settings
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.secret = os.getenv(settings.shared_secret_env, "").strip()
        if not self.secret:
            raise AutomationError(
                f"gateway secret environment variable is missing: "
                f"{settings.shared_secret_env}"
            )

    def _decode(self, response) -> dict[str, Any]:
        try:
            payload = json.loads(response.read().decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AutomationError("gateway returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise AutomationError("gateway returned a non-object JSON response")
        return payload

    def health(self) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self.settings.base_url}/api/android-gateway/v1/health",
            method="GET",
        )
        try:
            with self.opener.open(
                request,
                timeout=self.settings.request_timeout_seconds,
            ) as response:
                return self._decode(response)
        except (OSError, urllib.error.URLError) as exc:
            raise AutomationError(f"gateway health check failed: {exc}") from exc

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        last_error: BaseException | None = None
        for attempt in range(self.settings.max_attempts):
            timestamp = int(time.time())
            request = urllib.request.Request(
                f"{self.settings.base_url}{path}",
                data=body,
                headers=_signed_headers(self.secret, body, timestamp),
                method="POST",
            )
            try:
                with self.opener.open(
                    request,
                    timeout=self.settings.request_timeout_seconds,
                ) as response:
                    return self._decode(response)
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                if exc.code < 500:
                    raise AutomationError(
                        f"gateway rejected request ({exc.code}): {detail}"
                    ) from exc
                last_error = exc
            except (OSError, urllib.error.URLError) as exc:
                last_error = exc
            if attempt + 1 < self.settings.max_attempts:
                time.sleep(min(2**attempt, 4))
        raise AutomationError(f"gateway request failed: {last_error}")

    def submit(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("/api/android-gateway/v1/events", payload)

    def receipt(self, event_id: str, outcome: str) -> dict[str, Any]:
        return self._post(
            f"/api/android-gateway/v1/events/{event_id}/receipt",
            {"outcome": outcome},
        )


class GatewayDeliveryStore:
    def __init__(self, path: Path):
        self.path = path

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "pending": None, "completed": {}}
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if (
            data.get("version") != 1
            or not isinstance(data.get("completed"), dict)
            or (data.get("pending") is not None and not isinstance(data["pending"], dict))
        ):
            raise ValueError(f"unsupported gateway state file: {self.path}")
        return data

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{self.path.name}.",
            suffix=".tmp",
            dir=self.path.parent,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
            os.replace(temporary, self.path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise

    def pending(self) -> dict[str, Any] | None:
        return self._read()["pending"]

    def is_completed(self, event_id: str) -> bool:
        return event_id in self._read()["completed"]

    def begin(self, event: dict[str, Any]) -> bool:
        data = self._read()
        event_id = str(event["event_id"])
        if event_id in data["completed"]:
            return False
        pending = data["pending"]
        if pending is not None:
            if pending.get("event", {}).get("event_id") != event_id:
                raise AutomationError("another gateway message is still in flight")
            return False
        data["pending"] = {
            "event": event,
            "phase": "extracted",
            "decision": None,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        self._write(data)
        return True

    def set_decision(self, event_id: str, decision: dict[str, Any]) -> None:
        data = self._read()
        self._require_pending(data, event_id)
        data["pending"]["decision"] = decision
        data["pending"]["phase"] = "decided"
        data["pending"]["updated_at"] = datetime.now(UTC).isoformat()
        self._write(data)

    def set_phase(self, event_id: str, phase: str) -> None:
        data = self._read()
        self._require_pending(data, event_id)
        data["pending"]["phase"] = phase
        data["pending"]["updated_at"] = datetime.now(UTC).isoformat()
        self._write(data)

    def complete(self, event_id: str, outcome: str) -> None:
        data = self._read()
        pending = self._require_pending(data, event_id)
        decision = pending.get("decision") or {}
        data["completed"][event_id] = {
            "outcome": outcome,
            "reply_sha256": hashlib.sha256(
                str(decision.get("text") or "").encode("utf-8")
            ).hexdigest(),
            "completed_at": datetime.now(UTC).isoformat(),
        }
        data["pending"] = None
        self._write(data)

    @staticmethod
    def _require_pending(data: dict[str, Any], event_id: str) -> dict[str, Any]:
        pending = data.get("pending")
        if pending is None or pending.get("event", {}).get("event_id") != event_id:
            raise ValueError(f"gateway event is not pending: {event_id}")
        return pending


class GatewayWorkflow:
    def __init__(
        self,
        config: AutomationConfig,
        device: GatewayDevicePort,
        client: GatewayClientPort,
        store: GatewayDeliveryStore,
    ):
        if config.gateway is None:
            raise ValueError("gateway configuration is missing")
        self.config = config
        self.settings = config.gateway
        self.device = device
        self.client = client
        self.store = store

    def process(self, notification: NotificationEvent) -> GatewayResult:
        if not notification.message_candidate or not notification.title:
            raise DeviceStateError("notification is not a routable message")
        health = self.client.health()
        if not health.get("ok") or not health.get("enabled"):
            raise AutomationError("gateway server is not ready")

        xml = self.device.open_notification(notification.title)
        event = self._event_from_chat(notification, xml)
        self.store.begin(event)
        return self._finish_open_chat(event, xml)

    def resume(self) -> GatewayResult:
        pending = self.store.pending()
        if pending is None:
            raise AutomationError("there is no pending gateway delivery to resume")
        self.device.ensure_chat()
        return self._finish_open_chat(
            pending["event"],
            self.device.dump_hierarchy(),
        )

    def _finish_open_chat(
        self,
        event: dict[str, Any],
        xml: str,
    ) -> GatewayResult:
        try:
            result = self._continue(event, xml)
        except BaseException:
            # Preserve the current chat for an explicit or supervised resume.
            raise
        self.device.return_home()
        return result

    def _event_from_chat(
        self,
        notification: NotificationEvent,
        xml: str,
    ) -> dict[str, Any]:
        width, height = self.device.display_size()
        candidates = incoming_chat_messages(xml, width=width, height=height)
        if not candidates:
            raise DeviceStateError("no incoming chat message was exposed")
        body = candidates[-1].value
        event_id = hashlib.sha256(
            f"{notification.fingerprint}\0{body}".encode("utf-8")
        ).hexdigest()
        return {
            "event_id": event_id,
            "device_id": self.settings.device_id,
            "account_id": self.settings.account_id,
            "notification_id": notification.fingerprint,
            "sender_label": notification.title,
            "body": body,
            "observed_at": notification.observed_at,
        }

    def _continue(self, event: dict[str, Any], xml: str) -> GatewayResult:
        event_id = str(event["event_id"])
        if self.store.is_completed(event_id):
            return self._result(
                event,
                GatewayStatus.SKIPPED_DUPLICATE,
                reason="local_event_already_completed",
            )

        pending = self.store.pending()
        if pending is None:
            self.store.begin(event)
            pending = self.store.pending()
        if pending is None:
            raise AutomationError("gateway pending state was not persisted")
        phase = str(pending.get("phase") or "extracted")

        if phase == "sending":
            return self._settle(
                event,
                "send_unconfirmed",
                GatewayStatus.SEND_UNCONFIRMED,
                sent_clicks=0,
            )
        if phase == "sent":
            return self._settle(
                event,
                "sent",
                GatewayStatus.SENT,
                sent_clicks=0,
            )
        if phase == "send_unconfirmed":
            return self._settle(
                event,
                "send_unconfirmed",
                GatewayStatus.SEND_UNCONFIRMED,
                sent_clicks=0,
            )

        decision = pending.get("decision")
        if phase == "extracted":
            response = self.client.submit(event)
            decision = response.get("decision")
            if not isinstance(decision, dict):
                raise AutomationError("gateway response has no decision")
            self.store.set_decision(event_id, decision)
            phase = "decided"
        if phase != "decided" or not isinstance(decision, dict):
            raise AutomationError(f"unsupported gateway delivery phase: {phase}")

        action = str(decision.get("action") or "")
        if action == "noop":
            return self._settle(
                event,
                "skipped",
                GatewayStatus.NO_REPLY,
                reason=str(decision.get("reason") or "no_reply"),
            )
        if action == "unsupported":
            return self._settle(
                event,
                "failed",
                GatewayStatus.UNSUPPORTED,
                reason=str(decision.get("reason") or "unsupported"),
            )
        if action != "reply":
            raise AutomationError(f"unsupported gateway decision action: {action}")

        reply = str(decision.get("text") or "").strip()
        if not reply:
            raise AutomationError("gateway reply decision has empty text")
        self._verify_latest_incoming(event["body"], xml)
        before_count = len(find_text(xml, reply, case_sensitive=True))

        # This durable boundary deliberately gives at-most-once UI clicks.
        self.store.set_phase(event_id, "sending")
        self.device.prepare_reply(reply)
        self.device.send_once()
        confirmed = self._wait_for_increment(reply, before_count)
        outcome = "sent" if confirmed else "send_unconfirmed"
        status = GatewayStatus.SENT if confirmed else GatewayStatus.SEND_UNCONFIRMED
        self.store.set_phase(event_id, outcome)
        return self._settle(
            event,
            outcome,
            status,
            sent_clicks=1,
        )

    def _verify_latest_incoming(self, expected: str, xml: str) -> None:
        width, height = self.device.display_size()
        candidates = incoming_chat_messages(xml, width=width, height=height)
        if not candidates or candidates[-1].value != expected:
            raise DeviceStateError("current chat no longer ends with the routed message")

    def _wait_for_increment(self, reply: str, before_count: int) -> bool:
        deadline = time.monotonic() + self.config.timings.send_timeout_seconds
        while time.monotonic() < deadline:
            current = len(
                find_text(
                    self.device.dump_hierarchy(),
                    reply,
                    case_sensitive=True,
                )
            )
            if current > before_count:
                return True
            time.sleep(self.config.timings.poll_seconds)
        return False

    def _settle(
        self,
        event: dict[str, Any],
        outcome: str,
        status: GatewayStatus,
        *,
        reason: str | None = None,
        sent_clicks: int = 0,
    ) -> GatewayResult:
        event_id = str(event["event_id"])
        self.client.receipt(event_id, outcome)
        pending = self.store.pending() or {}
        decision = pending.get("decision") or {}
        self.store.complete(event_id, outcome)
        return self._result(
            event,
            status,
            decision_source=decision.get("source"),
            reason=reason or decision.get("reason"),
            sent_clicks=sent_clicks,
        )

    @staticmethod
    def _result(
        event: dict[str, Any],
        status: GatewayStatus,
        *,
        decision_source: str | None = None,
        reason: str | None = None,
        sent_clicks: int = 0,
    ) -> GatewayResult:
        return GatewayResult(
            status=status,
            event_id=str(event["event_id"]),
            sender=str(event["sender_label"]),
            body=str(event["body"]),
            decision_source=decision_source,
            reason=reason,
            sent_clicks=sent_clicks,
        )
