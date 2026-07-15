"""社内規程RAG+承認 API(FastAPI). 文書投入 -> 引用必須QA -> 承認フロー. テナント分離.
`uvicorn service.api:app --reload`
"""
from rag_agent import (
    DocumentStore, ingest_markdown, Retriever, QAAgent,
    ApprovalStore, ApprovalPolicy, extract_amount, SlackNotifier, AuditLog,
)
from .db import ServiceDB
from .report_html import build_html_report

DB = ServiceDB(":memory:")
POLICY = ApprovalPolicy()


def _qa_agent(tenant: str) -> QAAgent:
    store = DocumentStore()
    store.extend(DB.get_chunks(tenant))
    return QAAgent(Retriever(store))


def create_app():  # pragma: no cover
    from fastapi import Depends, FastAPI, Header, HTTPException
    from fastapi.responses import HTMLResponse
    from pydantic import BaseModel

    app = FastAPI(title="Dify RAG Approval Agent", version="1.0.0")
    approvals = {}  # tenant -> ApprovalStore

    def tenant(x_tenant_id: str = Header(...)) -> str:
        if not x_tenant_id:
            raise HTTPException(401, "tenant required")
        return x_tenant_id

    def _store(t: str) -> ApprovalStore:
        if t not in approvals:
            approvals[t] = ApprovalStore(notifier=SlackNotifier(), audit=AuditLog())
        return approvals[t]

    class DocIn(BaseModel):
        doc_id: str
        text: str

    class AskIn(BaseModel):
        question: str

    class ApprovalIn(BaseModel):
        requester: str
        title: str
        detail: str

    @app.post("/v1/docs")
    def add_docs(body: DocIn, t: str = Depends(tenant)):
        chunks = ingest_markdown(body.text, doc_id=body.doc_id)
        return {"added": DB.add_chunks(t, chunks)}

    @app.post("/v1/ask")
    def ask(body: AskIn, t: str = Depends(tenant)):
        ans = _qa_agent(t).ask(body.question)
        return ans.as_dict()

    @app.post("/v1/approvals")
    def create_approval(body: ApprovalIn, t: str = Depends(tenant)):
        route = POLICY.route(extract_amount(body.detail))
        store = _store(t)
        req = store.create(body.requester, body.title, body.detail)
        store.submit(req.id)
        store.decide(req.id, approver=route.required_approver, approve=True)
        DB.save_approval(t, req.id, body.requester, body.title, body.detail,
                         route.required_approver, "approved")
        return {"req_id": req.id, "required_approver": route.required_approver,
                "reason": route.reason, "status": "approved"}

    @app.get("/v1/report", response_class=HTMLResponse)
    def report(t: str = Depends(tenant)):
        return build_html_report(DB.list_approvals(t))

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    return app


try:  # pragma: no cover
    app = create_app()
except Exception:
    app = None
