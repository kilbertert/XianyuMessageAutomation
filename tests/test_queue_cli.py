import json
from pathlib import Path

from xianyu_automation.cli import main


def _config(tmp_path: Path) -> Path:
    root = Path(__file__).parents[1]
    data = json.loads((root / "config.example.json").read_text(encoding="utf-8"))
    data["serial"] = "test-device"
    data["inbound"]["queue_file"] = str(tmp_path / "pending.jsonl")
    data["inbound"]["consumer_state_file"] = str(
        tmp_path / "consumer-state.json"
    )
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _message() -> dict[str, str]:
    return {
        "fingerprint": "message-1",
        "notification_fingerprint": "notification-1",
        "sender": "x***3",
        "body": "AUTO_e2e_003",
        "observed_at": "2026-07-28T08:28:38+00:00",
        "queued_at": "2026-07-28T08:29:00+00:00",
    }


def test_queue_claim_cli_returns_message_for_worker(tmp_path, capsys) -> None:
    config_path = _config(tmp_path)
    message = _message()
    (tmp_path / "pending.jsonl").write_text(
        json.dumps(message) + "\n",
        encoding="utf-8",
    )

    exit_code = main(
        [
            "--config",
            str(config_path),
            "queue",
            "claim",
            "--worker-id",
            "worker-a",
            "--lease-seconds",
            "60",
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["type"] == "xianyu_queue_claim"
    assert output["claimed"] is True
    assert output["message"] == message
    assert output["attempts"] == 1


def test_queue_ack_cli_completes_owned_claim(tmp_path, capsys) -> None:
    config_path = _config(tmp_path)
    (tmp_path / "pending.jsonl").write_text(
        json.dumps(_message()) + "\n",
        encoding="utf-8",
    )
    main(
        [
            "--config",
            str(config_path),
            "queue",
            "claim",
            "--worker-id",
            "worker-a",
        ]
    )
    capsys.readouterr()

    exit_code = main(
        [
            "--config",
            str(config_path),
            "queue",
            "ack",
            "--worker-id",
            "worker-a",
            "--fingerprint",
            "message-1",
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["type"] == "xianyu_queue_ack"
    assert output["status"] == "done"
    assert output["fingerprint"] == "message-1"


def test_queue_fail_cli_dead_letters_at_attempt_limit(tmp_path, capsys) -> None:
    config_path = _config(tmp_path)
    (tmp_path / "pending.jsonl").write_text(
        json.dumps(_message()) + "\n",
        encoding="utf-8",
    )
    main(
        [
            "--config",
            str(config_path),
            "queue",
            "claim",
            "--worker-id",
            "worker-a",
        ]
    )
    capsys.readouterr()

    exit_code = main(
        [
            "--config",
            str(config_path),
            "queue",
            "fail",
            "--worker-id",
            "worker-a",
            "--fingerprint",
            "message-1",
            "--reason",
            "downstream unavailable",
            "--max-attempts",
            "1",
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["type"] == "xianyu_queue_fail"
    assert output["status"] == "dead"
    assert output["attempts"] == 1
