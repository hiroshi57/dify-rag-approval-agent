import pytest

from rag_agent import ApprovalPolicy, SessionStore, extract_amount, extract_amounts


# --- 金額抽出 ---
@pytest.mark.parametrize("text,expected", [
    ("5万円を精算したい", 50000),
    ("120,000円の備品", 120000),
    ("3万の交通費", 30000),
    ("8万円", 80000),
    ("１２０，０００円", 120000),          # 全角
    ("0.5万円", 5000),                     # 小数(旧実装は 50,000 と誤読)
    ("1万5000円", 15000),                  # 複合表記(旧実装は 10,000 と誤読)
    ("1億2000万円", 120_000_000),
    ("五万円", 50000),                     # 漢数字
    ("金額の記載なし", None),
    ("", None),
])
def test_extract_amount_variants(text, expected):
    assert extract_amount(text) == expected


def test_compound_amount_does_not_under_approve():
    """5万1000円 を 50,000円 と誤読すると上長承認に落ちてしまう(承認過少)."""
    amount = extract_amount("出張費5万1000円を精算したい")
    assert amount == 51000
    assert ApprovalPolicy().route(amount).required_approver == "部長"


def test_multiple_amounts_takes_max_and_warns():
    ex = extract_amounts("交通費3万円と宿泊費8万円")
    assert ex.amount == 80000
    assert ex.candidates == [30000, 80000]
    assert any("複数の金額" in w for w in ex.warnings)


def test_negative_amount_is_not_auto_routed():
    ex = extract_amounts("-3万円の返金")
    assert ex.amount is None
    assert any("負号" in w for w in ex.warnings)


def test_absurd_amount_is_rejected():
    ex = extract_amounts("99999999999999円")
    assert ex.amount is None
    assert any("上限" in w for w in ex.warnings)


def test_dates_are_not_amounts():
    assert extract_amount("締め日は毎月20日です") is None


# --- 承認ルーティング(規程第4条: 5万円超は部長) ---
def test_routing_manager_above_threshold():
    r = ApprovalPolicy().route(80000)
    assert r.required_approver == "部長"
    assert r.requires_manual_review is False


def test_routing_supervisor_at_or_below_threshold():
    assert ApprovalPolicy().route(50000).required_approver == "上長"
    assert ApprovalPolicy().route(30000).required_approver == "上長"


def test_unknown_amount_fails_closed():
    """金額不明を上長承認で素通ししない(fail-closed). 旧挙動は明示指定で選べる."""
    escalated = ApprovalPolicy().route(None)
    assert escalated.required_approver == "部長"
    assert escalated.requires_manual_review is True

    legacy = ApprovalPolicy(unknown_amount="supervisor").route(None)
    assert legacy.required_approver == "上長"
    assert legacy.requires_manual_review is True


def test_negative_amount_route_requires_review():
    r = ApprovalPolicy().route(-100)
    assert r.requires_manual_review is True


def test_custom_threshold():
    assert ApprovalPolicy(manager_threshold=100000).route(80000).required_approver == "上長"


def test_invalid_policy_config():
    with pytest.raises(ValueError):
        ApprovalPolicy(manager_threshold=-1)
    with pytest.raises(ValueError):
        ApprovalPolicy(unknown_amount="whatever")


def test_route_text_end_to_end():
    r = ApprovalPolicy().route_text("備品を8万円で購入したい")
    assert r.required_approver == "部長" and r.amount == 80000
    assert r.rule_ref == "経費精算規程 第4条"


# --- セッション(マルチターン) ---
def test_session_accumulates_history():
    store = SessionStore()
    s = store.create("user01")
    s.add("user", "こんにちは")
    s.add("assistant", "はい")
    assert s.turn_count == 2
    assert store.get(s.id).history[0].role == "user"


def test_session_rejects_unknown_role():
    with pytest.raises(ValueError):
        SessionStore().create("u").add("robot", "x")


def test_session_history_is_capped():
    store = SessionStore(max_turns=4)
    s = store.create("u")
    for i in range(10):
        s.add("user", str(i))
    assert s.turn_count == 4
    assert s.history[-1].text == "9"


def test_session_store_evicts_oldest():
    store = SessionStore(max_sessions=2)
    first = store.create("u1")
    store.create("u2")
    store.create("u3")
    assert len(store) == 2
    with pytest.raises(KeyError):
        store.get(first.id)


def test_missing_session_raises():
    with pytest.raises(KeyError):
        SessionStore().get("S-9999")


def test_session_ids_are_not_guessable_sequence():
    ids = {SessionStore().create("u").id for _ in range(5)}
    assert len(ids) == 5
