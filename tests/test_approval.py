import pytest

from rag_agent import (
    ApprovalError, ApprovalStore, AuditLog, SlackNotifier, classify_intent,
    detect_approval_intent, referenced_articles,
)


# --- 申請意図の判定 ---
@pytest.mark.parametrize("text", [
    "経費精算したいです",
    "有給を申請します",
    "備品を8万円で購入したい",
    "出張費の稟議を出します",
])
def test_detects_request_intent(text):
    assert detect_approval_intent(text) is True


@pytest.mark.parametrize("text", [
    "今日の天気は？",
    "有給休暇はどう申請する？",         # 質問であって申請ではない
    "誰の承認が必要ですか",             # 旧実装は "承認" の部分一致で申請と誤判定
    "経費精算の締め日はいつ？",
    "在宅勤務は可能か",
])
def test_questions_are_not_request_intent(text):
    assert detect_approval_intent(text) is False


def test_intent_result_explains_reason():
    r = classify_intent("経費精算したいです")
    assert r.is_request and "申請表現" in r.reason
    assert bool(r) is True


def test_referenced_articles():
    assert referenced_articles("第4条および第12条の定めによる") == ["第4条", "第12条"]


# --- 承認フロー ---
def test_full_approval_flow_and_slack_notify():
    notifier = SlackNotifier()   # dry-run
    audit = AuditLog()
    store = ApprovalStore(notifier=notifier, audit=audit)

    req = store.create("user01", "出張費精算", "出張費5万円", required_approver="上長")
    assert req.status == "draft"
    store.submit(req.id)
    assert store.get(req.id).status == "submitted"
    store.decide(req.id, approver="mgr", approve=True)
    assert store.get(req.id).status == "approved"
    assert store.get(req.id).decided_by == "mgr"

    assert len(notifier.outbox) == 2         # submit と decide
    actions = [e.action for e in audit.entries]
    assert {"approval.created", "approval.submitted", "approval.approved"} <= set(actions)
    assert audit.verify() is True


def test_history_records_transitions():
    store = ApprovalStore()
    req = store.create("u", "t", "d")
    store.submit(req.id)
    store.decide(req.id, "mgr", approve=False, note="証憑不足")
    hist = store.get(req.id).history
    assert [h["to"] for h in hist] == ["submitted", "rejected"]
    assert hist[-1]["note"] == "証憑不足"


def test_self_approval_is_blocked():
    """職務分離(SoD): 申請者が自分で決裁できてはならない."""
    store = ApprovalStore()
    req = store.create("user01", "出張費", "5万円")
    store.submit(req.id)
    with pytest.raises(ApprovalError):
        store.decide(req.id, approver="user01", approve=True)
    assert store.get(req.id).status == "submitted"


def test_cannot_submit_twice():
    store = ApprovalStore()
    req = store.create("u", "t", "d")
    store.submit(req.id)
    with pytest.raises(ApprovalError):
        store.submit(req.id)


def test_cannot_decide_before_submit():
    store = ApprovalStore()
    req = store.create("u", "t", "d")
    with pytest.raises(ApprovalError):
        store.decide(req.id, "mgr", approve=True)


def test_cannot_decide_twice():
    store = ApprovalStore()
    req = store.create("u", "t", "d")
    store.submit(req.id)
    store.decide(req.id, "mgr", approve=True)
    with pytest.raises(ApprovalError):
        store.decide(req.id, "mgr2", approve=False)


def test_cancel_and_invalid_cancel():
    store = ApprovalStore()
    req = store.create("u", "t", "d")
    store.cancel(req.id, actor="u")
    assert store.get(req.id).status == "cancelled"
    with pytest.raises(ApprovalError):
        store.submit(req.id)


def test_create_validates_inputs():
    store = ApprovalStore()
    with pytest.raises(ApprovalError):
        store.create("", "t", "d")
    with pytest.raises(ApprovalError):
        store.create("u", "  ", "d")


def test_missing_request_raises():
    store = ApprovalStore()
    with pytest.raises(KeyError):
        store.get("REQ-9999")


def test_ids_are_unique_across_stores():
    """テナント毎に別ストアでも ID が衝突しない(旧実装は両方 REQ-0001 を採番)."""
    a, b = ApprovalStore(), ApprovalStore()
    assert a.create("u", "t", "d").id != b.create("u", "t", "d").id


def test_notification_failure_does_not_break_state():
    class BoomNotifier(SlackNotifier):
        def notify(self, message):
            raise RuntimeError("slack down")

    audit = AuditLog()
    store = ApprovalStore(notifier=BoomNotifier(), audit=audit)
    req = store.create("u", "t", "d")
    store.submit(req.id)                 # 例外は外に漏らさない
    assert store.get(req.id).status == "submitted"
    assert any(e.action == "notify.failed" for e in audit.entries)


def test_list_filters_by_status():
    store = ApprovalStore()
    r1 = store.create("u", "t1", "d")
    store.create("u", "t2", "d")
    store.submit(r1.id)
    assert [r.id for r in store.list(status="submitted")] == [r1.id]
    assert len(store.list()) == 2
