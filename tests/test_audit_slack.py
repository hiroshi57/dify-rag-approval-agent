import json

import pytest

from rag_agent import AuditLog, SlackNotifier
from rag_agent.audit import AuditEntry


def test_hash_chain_links_entries():
    log = AuditLog()
    a = log.record("u", "qa.answered", {"q": "x"})
    b = log.record("u", "approval.created", {"id": "R1"})
    assert a.seq == 1 and b.seq == 2
    assert b.prev_hash == a.hash
    assert log.verify() is True


def test_verify_detects_tampering():
    log = AuditLog()
    log.record("u", "approval.approved", {"id": "R1", "amount": 1000})
    entries = log._entries          # noqa: SLF001 - 改ざんを模擬するため内部に触れる
    forged = AuditEntry(**{**entries[0].as_dict(), "detail": {"id": "R1", "amount": 999999}})
    entries[0] = forged
    assert log.verify() is False


def test_entries_are_defensive_copies():
    log = AuditLog()
    log.record("u", "qa.answered", {"q": "x"})
    got = log.entries
    got.clear()
    assert len(log.entries) == 1
    d = log.entries[0].as_dict()
    d["detail"]["q"] = "tampered"
    assert log.entries[0].detail["q"] == "x"


def test_detail_is_snapshotted_at_record_time():
    log = AuditLog()
    detail = {"citations": ["第3条"]}
    log.record("u", "qa.answered", detail)
    detail["citations"].append("第5条")
    assert log.entries[0].detail["citations"] == ["第3条"]


def test_filter_by_action_and_actor():
    log = AuditLog()
    log.record("a", "qa.answered", {})
    log.record("b", "qa.refused", {})
    assert len(log.filter(action="qa.refused")) == 1
    assert len(log.filter(actor="a")) == 1


def test_jsonl_sink_appends(tmp_path):
    path = tmp_path / "audit" / "log.jsonl"
    log = AuditLog(sink_path=str(path))
    log.record("u", "qa.answered", {"q": "x"})
    log.record("u", "qa.refused", {"q": "y"})
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["action"] == "qa.answered"


def test_to_jsonl_roundtrip():
    log = AuditLog()
    log.record("u", "qa.answered", {"q": "日本語"})
    payload = json.loads(log.to_jsonl())
    assert payload["detail"]["q"] == "日本語"


# --- Slack ---
def test_dry_run_result_is_explicit():
    n = SlackNotifier()
    result = n.notify("hello")
    assert result.dry_run is True and result.delivered is False
    assert n.outbox == ["hello"]


def test_rejects_non_https_webhook():
    with pytest.raises(ValueError):
        SlackNotifier("http://hooks.slack.com/services/x")


def test_rejects_untrusted_host():
    with pytest.raises(ValueError):
        SlackNotifier("https://evil.example.com/hook")


def test_message_is_truncated():
    n = SlackNotifier()
    n.notify("あ" * 5000)
    assert len(n.outbox[0]) == 3000
