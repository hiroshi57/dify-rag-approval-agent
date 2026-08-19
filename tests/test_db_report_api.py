import pytest

from rag_agent import ingest_markdown
from service.db import ServiceDB
from service.report_html import build_html_report

POLICY = """# 経費精算規程
第3条（締め日）
経費精算の締め日は毎月20日とする。
第4条（申請方法）
5万円を超える経費は部長承認を必要とする。
"""


# --- DB ---
def test_chunks_roundtrip_and_tenant_isolation():
    db = ServiceDB(":memory:")
    db.add_chunks("t-a", ingest_markdown(POLICY, doc_id="expense_policy"))
    assert len(db.get_chunks("t-a")) >= 1
    assert db.get_chunks("t-b") == []      # 越境不可


def test_chunk_insert_is_idempotent():
    db = ServiceDB(":memory:")
    chunks = ingest_markdown(POLICY, doc_id="expense_policy")
    assert db.add_chunks("t-a", chunks) == len(chunks)
    assert db.add_chunks("t-a", chunks) == 0        # 同じ文書の二重投入で重複しない
    assert len(db.get_chunks("t-a")) == len(chunks)


def test_chunks_revision_changes_on_write():
    db = ServiceDB(":memory:")
    before = db.chunks_revision("t-a")
    db.add_chunks("t-a", ingest_markdown(POLICY, doc_id="expense_policy"))
    assert db.chunks_revision("t-a") != before


def test_invalid_tenant_is_rejected():
    db = ServiceDB(":memory:")
    for bad in ["", "../etc", "a" * 65, "te nant"]:
        with pytest.raises(ValueError):
            db.get_chunks(bad)


def test_approvals_persist_isolated():
    db = ServiceDB(":memory:")
    db.save_approval("t-a", "REQ-0001", "u", "出張費", "5万円", "上長", "approved")
    assert len(db.list_approvals("t-a")) == 1
    assert db.list_approvals("t-b") == []


def test_duplicate_request_id_is_rejected():
    db = ServiceDB(":memory:")
    db.save_approval("t-a", "REQ-1", "u", "t", "d", "", "draft")
    with pytest.raises(Exception):
        db.save_approval("t-a", "REQ-1", "u", "t", "d", "", "draft")
    # テナントが違えば同じ ID を持てる
    db.save_approval("t-b", "REQ-1", "u", "t", "d", "", "draft")


def test_invalid_status_is_rejected_by_schema():
    db = ServiceDB(":memory:")
    with pytest.raises(Exception):
        db.save_approval("t-a", "REQ-2", "u", "t", "d", "", "not-a-status")


def test_update_and_get_approval():
    db = ServiceDB(":memory:")
    db.save_approval("t-a", "REQ-3", "u", "t", "d", "", "submitted")
    assert db.update_approval("t-a", "REQ-3", "approved", approver="mgr") == 1
    row = db.get_approval("t-a", "REQ-3")
    assert row["status"] == "approved" and row["approver"] == "mgr"
    assert db.update_approval("t-b", "REQ-3", "rejected") == 0      # 越境更新は不可


def test_audit_persistence_and_isolation():
    db = ServiceDB(":memory:")
    db.append_audit("t-a", {"seq": 1, "ts": "t", "actor": "u", "action": "qa.answered",
                            "detail": {"q": "x"}, "prev_hash": "0", "hash": "h"})
    rows = db.list_audit("t-a")
    assert rows[0]["detail"] == {"q": "x"}
    assert db.list_audit("t-b") == []


# --- HTML レポート ---
def test_html_report():
    html = build_html_report([{"req_id": "REQ-0001", "title": "出張費", "requester": "u",
                               "approver": "部長", "status": "approved", "amount": 80000}])
    assert "承認状況レポート" in html and "REQ-0001" in html and "承認済" in html
    assert "80,000円" in html


def test_html_report_escapes_all_fields():
    html = build_html_report([{"req_id": "<img src=x>", "title": "<b>x</b>",
                               "requester": "<script>a</script>", "approver": "",
                               "status": "<script>alert(1)</script>"}])
    assert "<script>" not in html and "<img" not in html and "<b>x</b>" not in html
    assert "&lt;b&gt;" in html


def test_html_report_empty_state():
    assert "対象の承認申請はありません" in build_html_report([])


# --- API E2E ---
@pytest.fixture()
def client():
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    from service.api import AppContext, create_app
    return TestClient(create_app(AppContext(db=ServiceDB(":memory:"), api_keys={})))


HA = {"X-Tenant-Id": "t-a"}
HB = {"X-Tenant-Id": "t-b"}


def test_api_qa_and_tenant_isolation(client):
    client.post("/v1/docs", json={"doc_id": "expense_policy", "text": POLICY}, headers=HA)
    ans = client.post("/v1/ask", json={"question": "経費精算の締め日は?"}, headers=HA).json()
    assert ans["answered"] is True and ans["citations"]
    assert ans["citations"][0]["label"].startswith("経費精算規程")
    ans_b = client.post("/v1/ask", json={"question": "経費精算の締め日は?"}, headers=HB).json()
    assert ans_b["answered"] is False and ans_b["citations"] == []


def test_api_reindexes_after_new_docs(client):
    """検索インデックスのキャッシュが文書追加で更新されること."""
    assert client.post("/v1/ask", json={"question": "締め日は?"},
                       headers=HA).json()["answered"] is False
    client.post("/v1/docs", json={"doc_id": "expense_policy", "text": POLICY}, headers=HA)
    assert client.post("/v1/ask", json={"question": "締め日は?"},
                       headers=HA).json()["answered"] is True


def test_api_approval_is_not_auto_approved(client):
    """起票と決裁は分離されている(旧実装は起票と同時に自動承認していた)."""
    r = client.post("/v1/approvals", json={"requester": "u", "title": "出張費",
                                           "detail": "出張費8万円を精算"}, headers=HA)
    assert r.status_code == 201
    body = r.json()
    assert body["required_approver"] == "部長"
    assert body["status"] == "submitted"

    req_id = body["req_id"]
    listed = client.get("/v1/approvals", headers=HA).json()["items"]
    assert listed[0]["status"] == "submitted"

    decided = client.post(f"/v1/approvals/{req_id}/decide",
                          json={"approver": "mgr", "approve": True}, headers=HA)
    assert decided.status_code == 200 and decided.json()["status"] == "approved"
    assert client.get("/v1/approvals", headers=HA).json()["items"][0]["approver"] == "mgr"


def test_api_self_approval_rejected(client):
    req_id = client.post("/v1/approvals", json={"requester": "u", "title": "t", "detail": "3万円"},
                         headers=HA).json()["req_id"]
    r = client.post(f"/v1/approvals/{req_id}/decide",
                    json={"approver": "u", "approve": True}, headers=HA)
    assert r.status_code == 409


def test_api_decide_unknown_request(client):
    r = client.post("/v1/approvals/REQ-UNKNOWN/decide",
                    json={"approver": "mgr", "approve": True}, headers=HA)
    assert r.status_code == 404


def test_api_amount_unknown_requires_manual_review(client):
    body = client.post("/v1/approvals", json={"requester": "u", "title": "備品",
                                              "detail": "金額未定"}, headers=HA).json()
    assert body["requires_manual_review"] is True
    assert body["required_approver"] == "部長"


def test_api_audit_is_recorded_and_chained(client):
    client.post("/v1/docs", json={"doc_id": "expense_policy", "text": POLICY}, headers=HA)
    client.post("/v1/ask", json={"question": "締め日は?"}, headers=HA)
    client.post("/v1/ask", json={"question": "宇宙の年齢は?"}, headers=HA)
    audit = client.get("/v1/audit", headers=HA).json()
    actions = [e["action"] for e in audit["entries"]]
    assert "qa.answered" in actions and "qa.refused" in actions
    assert audit["chain_valid"] is True
    assert client.get("/v1/audit", headers=HB).json()["entries"] == []


def test_api_chat_routes_question_to_qa(client):
    client.post("/v1/docs", json={"doc_id": "expense_policy", "text": POLICY}, headers=HA)
    body = client.post("/v1/chat", json={"message": "有給休暇はどう申請する？"}, headers=HA).json()
    assert body["type"] == "answer"          # 質問を承認フローへ流さない
    body2 = client.post("/v1/chat", json={"message": "8万円の備品を購入したい"},
                        headers=HA).json()
    assert body2["type"] == "approval_suggestion" and body2["required_approver"] == "部長"


def test_api_report(client):
    client.post("/v1/approvals", json={"requester": "u", "title": "出張費",
                                       "detail": "8万円"}, headers=HA)
    r = client.get("/v1/report", headers=HA)
    assert r.status_code == 200 and "承認状況レポート" in r.text


def test_api_requires_tenant_header(client):
    assert client.post("/v1/ask", json={"question": "x"}).status_code == 422
    assert client.post("/v1/ask", json={"question": "x"},
                       headers={"X-Tenant-Id": "bad tenant"}).status_code == 400


def test_api_validates_payload(client):
    assert client.post("/v1/ask", json={"question": ""}, headers=HA).status_code == 422
    assert client.post("/v1/ask", json={"question": "a" * 2000},
                       headers=HA).status_code == 422


def test_dev_open_mode_is_flagged(client):
    assert client.get("/healthz").json()["auth_enabled"] is False
    assert client.post("/v1/ask", json={"question": "x"},
                       headers=HA).headers.get("X-Auth-Mode") == "dev-open"


def test_api_key_auth_enforced():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from service.api import AppContext, create_app, load_api_keys

    ctx = AppContext(db=ServiceDB(":memory:"), api_keys={"t-a": "secret"})
    c = TestClient(create_app(ctx))
    assert c.post("/v1/ask", json={"question": "x"}, headers=HA).status_code == 401
    assert c.post("/v1/ask", json={"question": "x"},
                  headers={**HA, "X-API-Key": "wrong"}).status_code == 401
    ok = c.post("/v1/ask", json={"question": "締め日は?"},
                headers={**HA, "X-API-Key": "secret"})
    assert ok.status_code == 200
    # 認証済みでも他テナントの鍵では入れない
    assert c.post("/v1/ask", json={"question": "x"},
                  headers={**HB, "X-API-Key": "secret"}).status_code == 401
    assert load_api_keys("t-a:secret, t-b:k2") == {"t-a": "secret", "t-b": "k2"}
