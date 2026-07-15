import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from service.db import ServiceDB  # noqa: E402
from service.report_html import build_html_report  # noqa: E402
from rag_agent import ingest_markdown  # noqa: E402

POLICY = """# 経費精算規程
第3条（締め日）
経費精算の締め日は毎月20日とする。
"""


def test_chunks_roundtrip_and_tenant_isolation():
    db = ServiceDB(":memory:")
    db.add_chunks("t-a", ingest_markdown(POLICY, doc_id="経費精算規程"))
    assert len(db.get_chunks("t-a")) >= 1
    assert db.get_chunks("t-b") == []      # 越境不可


def test_approvals_persist_isolated():
    db = ServiceDB(":memory:")
    db.save_approval("t-a", "REQ-0001", "u", "出張費", "5万円", "上長", "approved")
    assert len(db.list_approvals("t-a")) == 1
    assert db.list_approvals("t-b") == []


def test_html_report():
    html = build_html_report([{"req_id": "REQ-0001", "title": "出張費", "requester": "u",
                               "approver": "部長", "status": "approved"}])
    assert "承認状況レポート" in html and "REQ-0001" in html and "承認済" in html


def test_html_report_escapes():
    html = build_html_report([{"req_id": "R", "title": "<b>x</b>", "requester": "u",
                               "approver": "", "status": "draft"}])
    assert "<b>x</b>" not in html and "&lt;b&gt;" in html


def test_api_e2e_and_tenant_isolation():
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    from service.api import create_app
    c = TestClient(create_app())
    ha, hb = {"X-Tenant-Id": "t-a"}, {"X-Tenant-Id": "t-b"}
    c.post("/v1/docs", json={"doc_id": "経費精算規程", "text": POLICY}, headers=ha)
    # tenant-a は締め日を引用付きで回答
    ans = c.post("/v1/ask", json={"question": "経費精算の締め日は?"}, headers=ha).json()
    assert ans["answered"] is True and ans["citations"]
    # tenant-b は文書なし -> 引用できず回答拒否
    ans_b = c.post("/v1/ask", json={"question": "経費精算の締め日は?"}, headers=hb).json()
    assert ans_b["answered"] is False
    # 承認ルーティング(5万円超->部長)
    appr = c.post("/v1/approvals", json={"requester": "u", "title": "出張費",
                                         "detail": "出張費8万円を精算"}, headers=ha).json()
    assert appr["required_approver"] == "部長"
    r = c.get("/v1/report", headers=ha)
    assert r.status_code == 200 and "承認状況レポート" in r.text
