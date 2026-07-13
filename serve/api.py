"""実行可能な FastAPI サービス(Difyのリファレンス実装).

`uvicorn serve.api:app --reload` で起動。QA(引用必須) / 承認 / 監査 を提供。
FastAPI 未インストールでも rag_agent コアはテスト可能(この import は遅延)。
"""
from __future__ import annotations

import os

from rag_agent import (
    DocumentStore, ingest_dir, Retriever, QAAgent, AuditLog,
    ApprovalStore, detect_approval_intent, SlackNotifier,
)
from rag_agent.policy import ApprovalPolicy, extract_amount
from rag_agent.session import SessionStore

DOCS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs")

AUDIT = AuditLog()
STORE = DocumentStore()
STORE.extend(ingest_dir(DOCS))
AGENT = QAAgent(Retriever(STORE), audit=AUDIT)
APPROVALS = ApprovalStore(notifier=SlackNotifier(), audit=AUDIT)
POLICY = ApprovalPolicy()
SESSIONS = SessionStore()


def create_app():  # pragma: no cover
    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel

    app = FastAPI(title="dify-rag-approval-agent", version="0.2.0")

    class ChatReq(BaseModel):
        message: str
        actor: str = "anonymous"
        session_id: str | None = None

    class ApprovalReq(BaseModel):
        requester: str
        title: str
        detail: str

    @app.post("/v1/chat")
    def chat(req: ChatReq):
        session = SESSIONS.get(req.session_id) if req.session_id else SESSIONS.create(req.actor)
        session.add("user", req.message)
        # 申請意図なら承認ルーティングを提示
        if detect_approval_intent(req.message):
            amount = extract_amount(req.message)
            route = POLICY.route(amount)
            reply = f"承認申請として受け付け可能です。{route.reason}(承認者: {route.required_approver})"
            session.add("assistant", reply)
            return {"session_id": session.id, "type": "approval_suggestion",
                    "amount": amount, "required_approver": route.required_approver, "text": reply}
        ans = AGENT.ask(req.message, actor=req.actor)
        session.add("assistant", ans.text)
        return {"session_id": session.id, "type": "answer", **ans.as_dict()}

    @app.post("/v1/approvals")
    def create_approval(req: ApprovalReq):
        r = APPROVALS.create(req.requester, req.title, req.detail)
        route = POLICY.route(extract_amount(req.detail))
        APPROVALS.submit(r.id)
        return {"id": r.id, "status": r.status, "required_approver": route.required_approver}

    @app.get("/v1/audit")
    def audit():
        return {"entries": [e.as_dict() for e in AUDIT.entries]}

    @app.get("/healthz")
    def healthz():
        return {"status": "ok", "chunks": len(STORE)}

    return app


try:  # pragma: no cover
    app = create_app()
except Exception:
    app = None
