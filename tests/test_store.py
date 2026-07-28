import json

from xianyu_automation.store import StateStore, fingerprint


def test_state_store_records_hashes_not_plaintext(tmp_path) -> None:
    path = tmp_path / "state.json"
    store = StateStore(path)
    key = fingerprint("AUTO_E2E_001", "row-y:925")

    assert not store.contains(key)
    store.record_sent(key, "收到，这是自动化联调测试。")
    assert store.contains(key)

    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    assert "AUTO_E2E_001" not in raw
    assert "自动化联调测试" not in raw
    assert key in data["processed"]
