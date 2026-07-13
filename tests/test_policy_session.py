import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from rag_agent import ApprovalPolicy, extract_amount, SessionStore  # noqa: E402


# --- 金額抽出 ---
def test_extract_amount_variants():
    assert extract_amount("5万円を精算したい") == 50000
    assert extract_amount("120,000円の備品") == 120000
    assert extract_amount("3万の交通費") == 30000
    assert extract_amount("金額の記載なし") is None


# --- 承認ルーティング(規程第4条: 5万円超は部長) ---
def test_routing_manager_above_threshold():
    r = ApprovalPolicy().route(80000)
    assert r.required_approver == "部長"


def test_routing_supervisor_at_or_below_threshold():
    assert ApprovalPolicy().route(50000).required_approver == "上長"
    assert ApprovalPolicy().route(30000).required_approver == "上長"


def test_routing_unknown_amount_defaults_supervisor():
    assert ApprovalPolicy().route(None).required_approver == "上長"


def test_custom_threshold():
    assert ApprovalPolicy(manager_threshold=100000).route(80000).required_approver == "上長"


# --- セッション(マルチターン) ---
def test_session_accumulates_history():
    store = SessionStore()
    s = store.create("user01")
    s.add("user", "こんにちは")
    s.add("assistant", "はい")
    assert s.turn_count == 2
    assert store.get(s.id).history[0].role == "user"


def test_missing_session_raises():
    with pytest.raises(KeyError):
        SessionStore().get("S-9999")
