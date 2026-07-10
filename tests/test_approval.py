import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from rag_agent import (  # noqa: E402
    ApprovalStore, detect_approval_intent, AuditLog, SlackNotifier,
)


def test_detect_intent():
    assert detect_approval_intent("経費精算したいです") is True
    assert detect_approval_intent("有給を申請します") is True
    assert detect_approval_intent("今日の天気は？") is False


def test_full_approval_flow_and_slack_notify():
    notifier = SlackNotifier()   # dry-run
    audit = AuditLog()
    store = ApprovalStore(notifier=notifier, audit=audit)

    req = store.create("user01", "出張費精算", "出張費5万円")
    assert req.status == "draft"
    store.submit(req.id)
    assert store.get(req.id).status == "submitted"
    store.decide(req.id, approver="mgr", approve=True)
    assert store.get(req.id).status == "approved"

    # Slack は submit と decide の2回(dry-run outbox に蓄積)
    assert len(notifier.outbox) == 2
    # 監査ログに承認遷移が残る
    actions = [e.action for e in audit.entries]
    assert "approval.created" in actions
    assert "approval.submitted" in actions
    assert "approval.approved" in actions


def test_cannot_submit_twice():
    store = ApprovalStore()
    req = store.create("u", "t", "d")
    store.submit(req.id)
    with pytest.raises(ValueError):
        store.submit(req.id)


def test_cannot_decide_before_submit():
    store = ApprovalStore()
    req = store.create("u", "t", "d")
    with pytest.raises(ValueError):
        store.decide(req.id, "mgr", approve=True)


def test_missing_request_raises():
    store = ApprovalStore()
    with pytest.raises(KeyError):
        store.get("REQ-9999")
