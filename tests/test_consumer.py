import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest

from xianyu_automation.consumer import QueueConsumer


def _write_messages(path) -> list[dict[str, str]]:
    messages = [
        {
            "fingerprint": "message-1",
            "notification_fingerprint": "notification-1",
            "sender": "x***3",
            "body": "AUTO_e2e_003",
            "observed_at": "2026-07-28T08:28:38+00:00",
            "queued_at": "2026-07-28T08:29:00+00:00",
        },
        {
            "fingerprint": "message-2",
            "notification_fingerprint": "notification-2",
            "sender": "buyer-2",
            "body": "second message",
            "observed_at": "2026-07-28T08:30:00+00:00",
            "queued_at": "2026-07-28T08:31:00+00:00",
        },
    ]
    path.write_text(
        "".join(json.dumps(message) + "\n" for message in messages),
        encoding="utf-8",
    )
    return messages


def test_claim_returns_oldest_message_with_lease_and_keeps_state_private(tmp_path) -> None:
    queue_file = tmp_path / "pending.jsonl"
    state_file = tmp_path / "consumer-state.json"
    messages = _write_messages(queue_file)
    consumer = QueueConsumer(queue_file, state_file)
    now = datetime(2026, 7, 28, 10, 0, tzinfo=UTC)

    claim = consumer.claim("worker-a", lease_seconds=60, now=now)

    assert claim == {
        "message": messages[0],
        "attempts": 1,
        "worker_id": "worker-a",
        "lease_until": "2026-07-28T10:01:00+00:00",
    }
    state_raw = state_file.read_text(encoding="utf-8")
    assert "AUTO_e2e_003" not in state_raw
    assert "x***3" not in state_raw


def test_ack_completes_claim_and_next_claim_advances(tmp_path) -> None:
    queue_file = tmp_path / "pending.jsonl"
    state_file = tmp_path / "consumer-state.json"
    messages = _write_messages(queue_file)
    consumer = QueueConsumer(queue_file, state_file)
    claimed_at = datetime(2026, 7, 28, 10, 0, tzinfo=UTC)
    completed_at = datetime(2026, 7, 28, 10, 0, 10, tzinfo=UTC)
    consumer.claim("worker-a", lease_seconds=60, now=claimed_at)

    result = consumer.ack("message-1", "worker-a", now=completed_at)

    assert result == {
        "fingerprint": "message-1",
        "status": "done",
        "attempts": 1,
        "completed_at": "2026-07-28T10:00:10+00:00",
    }
    next_claim = consumer.claim("worker-a", lease_seconds=60, now=completed_at)
    assert next_claim is not None
    assert next_claim["message"] == messages[1]


def test_ack_rejects_non_owner_without_completing_message(tmp_path) -> None:
    queue_file = tmp_path / "pending.jsonl"
    state_file = tmp_path / "consumer-state.json"
    _write_messages(queue_file)
    consumer = QueueConsumer(queue_file, state_file)
    now = datetime(2026, 7, 28, 10, 0, tzinfo=UTC)
    consumer.claim("worker-a", lease_seconds=60, now=now)

    with pytest.raises(ValueError, match="another worker"):
        consumer.ack("message-1", "worker-b", now=now)

    result = consumer.ack("message-1", "worker-a", now=now)
    assert result["status"] == "done"


def test_expired_lease_is_redelivered_with_incremented_attempts(tmp_path) -> None:
    queue_file = tmp_path / "pending.jsonl"
    state_file = tmp_path / "consumer-state.json"
    messages = _write_messages(queue_file)
    queue_file.write_text(json.dumps(messages[0]) + "\n", encoding="utf-8")
    consumer = QueueConsumer(queue_file, state_file)
    first_at = datetime(2026, 7, 28, 10, 0, tzinfo=UTC)
    second_at = datetime(2026, 7, 28, 10, 1, 1, tzinfo=UTC)
    consumer.claim("worker-a", lease_seconds=60, now=first_at)

    claim = consumer.claim("worker-b", lease_seconds=60, now=second_at)

    assert claim is not None
    assert claim["message"] == messages[0]
    assert claim["attempts"] == 2
    assert claim["worker_id"] == "worker-b"


def test_expired_owner_cannot_ack_before_redelivery(tmp_path) -> None:
    queue_file = tmp_path / "pending.jsonl"
    state_file = tmp_path / "consumer-state.json"
    messages = _write_messages(queue_file)
    queue_file.write_text(json.dumps(messages[0]) + "\n", encoding="utf-8")
    consumer = QueueConsumer(queue_file, state_file)
    claimed_at = datetime(2026, 7, 28, 10, 0, tzinfo=UTC)
    expired_at = datetime(2026, 7, 28, 10, 1, 1, tzinfo=UTC)
    consumer.claim("worker-a", lease_seconds=60, now=claimed_at)

    with pytest.raises(ValueError, match="lease has expired"):
        consumer.ack("message-1", "worker-a", now=expired_at)

    claim = consumer.claim("worker-b", lease_seconds=60, now=expired_at)
    assert claim is not None
    assert claim["attempts"] == 2


def test_fail_retries_then_dead_letters_without_plaintext_error(tmp_path) -> None:
    queue_file = tmp_path / "pending.jsonl"
    state_file = tmp_path / "consumer-state.json"
    messages = _write_messages(queue_file)
    queue_file.write_text(json.dumps(messages[0]) + "\n", encoding="utf-8")
    consumer = QueueConsumer(queue_file, state_file)
    first_at = datetime(2026, 7, 28, 10, 0, tzinfo=UTC)
    second_at = datetime(2026, 7, 28, 10, 0, 1, tzinfo=UTC)
    reason = "temporary downstream failure"

    consumer.claim("worker-a", lease_seconds=60, now=first_at)
    retry = consumer.fail(
        "message-1",
        "worker-a",
        reason,
        max_attempts=2,
        now=first_at,
    )
    second_claim = consumer.claim("worker-b", lease_seconds=60, now=second_at)
    dead = consumer.fail(
        "message-1",
        "worker-b",
        reason,
        max_attempts=2,
        now=second_at,
    )

    assert retry["status"] == "pending"
    assert second_claim is not None
    assert second_claim["attempts"] == 2
    assert dead["status"] == "dead"
    assert consumer.claim("worker-c", lease_seconds=60, now=second_at) is None
    state_raw = state_file.read_text(encoding="utf-8")
    assert reason not in state_raw
    assert "AUTO_e2e_003" not in state_raw
    assert "last_error_sha256" in state_raw


def test_concurrent_workers_cannot_claim_the_same_message(tmp_path) -> None:
    queue_file = tmp_path / "pending.jsonl"
    state_file = tmp_path / "consumer-state.json"
    messages = _write_messages(queue_file)
    queue_file.write_text(json.dumps(messages[0]) + "\n", encoding="utf-8")
    barrier = threading.Barrier(2)
    now = datetime(2026, 7, 28, 10, 0, tzinfo=UTC)

    def claim(worker_id: str):
        barrier.wait()
        return QueueConsumer(queue_file, state_file).claim(
            worker_id,
            lease_seconds=60,
            now=now,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, ["worker-a", "worker-b"]))

    claims = [result for result in results if result is not None]
    assert len(claims) == 1
    assert claims[0]["message"]["fingerprint"] == "message-1"
