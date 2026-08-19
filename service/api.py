"""社内規程RAG + 承認 API(FastAPI).

  文書投入 -> 引用必須QA -> 承認申請 -> 決裁 -> 監査ログ / HTMLレポート

`uvicorn service.api:app --reload`

認証について(正直な但し書き):
  環境変数 `RAG_API_KEYS` に `tenant:key` をカンマ区切りで設定すると、
  `X-Tenant-Id` + `X-API-Key` の一致を必須にする(テナント分離が成立する)。
  未設定の場合は **開発用のオープンモード** で起動し、警告ログと
  `X-Auth-Mode: dev-open` レスポンスヘッダを返す。本番では必ず設定すること。
"""
from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

from rag_agent import (
    ApprovalError, ApprovalPolicy, ApprovalStore, AuditLog, DocumentStore, QAAgent,
    Retriever, SessionStore, SlackNotifier, classify_intent, ingest_markdown,
)
from .db import ServiceDB, validate_tenant
from .report_html import build_html_report

logger = logging.getLogger(__name__)

MAX_DOC_CHARS = 500_000
MAX_QUESTION_CHARS = 1_000
MAX_TEXT_FIELD = 2_000


def load_api_keys(env_value: Optional[str] = None) -> Dict[str, str]:
    """`tenant:key,tenant2:key2` 形式をパースする."""
    raw = env_value if env_value is not None else os.getenv("RAG_API_KEYS", "")
    keys: Dict[str, str] = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair:
            continue
        tenant, _, key = pair.partition(":")
        if tenant and key:
            keys[tenant.strip()] = key.strip()
    return keys


@dataclass
class TenantState:
    audit: AuditLog
    approvals: ApprovalStore
    retriever: Optional[Retriever] = None
    revision: int = -1
    lock: threading.Lock = field(default_factory=threading.Lock)


class AppContext:
    """アプリの依存をまとめる(モジュールグローバル共有をやめ、テスト毎に隔離する)."""

    def __init__(self, db: Optional[ServiceDB] = None,
                 policy: Optional[ApprovalPolicy] = None,
                 notifier: Optional[SlackNotifier] = None,
                 api_keys: Optional[Dict[str, str]] = None) -> None:
        self.db = db or ServiceDB(os.getenv("RAG_DB_PATH", ":memory:"))
        self.policy = policy or ApprovalPolicy()
        self.notifier = notifier or SlackNotifier(os.getenv("SLACK_WEBHOOK_URL"))
        self.api_keys = load_api_keys() if api_keys is None else dict(api_keys)
        self.sessions = SessionStore()
        self._tenants: Dict[str, TenantState] = {}
        self._lock = threading.Lock()
        if not self.api_keys:
            logger.warning(
                "RAG_API_KEYS 未設定のため認証なし(dev-open)で起動します。本番では設定してください。")

    @property
    def auth_enabled(self) -> bool:
        return bool(self.api_keys)

    def state(self, tenant: str) -> TenantState:
        with self._lock:
            if tenant not in self._tenants:
                audit = AuditLog()
                self._tenants[tenant] = TenantState(
                    audit=audit,
                    approvals=ApprovalStore(notifier=self.notifier, audit=audit))
            return self._tenants[tenant]

    # --- 監査: メモリ上のハッシュチェーンを DB にミラーする ---
    def persist_new_audit(self, tenant: str, since_seq: int) -> None:
        for e in self.state(tenant).audit.entries:
            if e.seq > since_seq:
                self.db.append_audit(tenant, e.as_dict())

    def audit_seq(self, tenant: str) -> int:
        entries = self.state(tenant).audit.entries
        return entries[-1].seq if entries else 0

    def qa_agent(self, tenant: str) -> QAAgent:
        """テナントのチャンク集合が変わった時だけ検索インデックスを作り直す."""
        st = self.state(tenant)
        rev = self.db.chunks_revision(tenant)
        with st.lock:
            if st.retriever is None or st.revision != rev:
                store = DocumentStore(self.db.get_chunks(tenant))
                st.retriever = Retriever(store)
                st.revision = rev
            return QAAgent(st.retriever, audit=st.audit)


def create_app(context: Optional[AppContext] = None):
    from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response
    from fastapi.responses import HTMLResponse
    from pydantic import BaseModel, Field

    ctx = context or AppContext()
    app = FastAPI(title="Dify RAG Approval Agent", version="1.1.0")
    app.state.ctx = ctx

    def tenant(x_tenant_id: str = Header(..., alias="X-Tenant-Id"),
               x_api_key: Optional[str] = Header(None, alias="X-API-Key")) -> str:
        try:
            validate_tenant(x_tenant_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if ctx.auth_enabled:
            expected = ctx.api_keys.get(x_tenant_id)
            if not expected or not x_api_key or x_api_key != expected:
                raise HTTPException(401, "認証に失敗しました(X-API-Key)")
        return x_tenant_id

    def _mark_auth_mode(response: Response) -> None:
        if not ctx.auth_enabled:
            response.headers["X-Auth-Mode"] = "dev-open"

    class DocIn(BaseModel):
        doc_id: str = Field(min_length=1, max_length=200)
        text: str = Field(min_length=1, max_length=MAX_DOC_CHARS)
        version: str = Field("", max_length=50)

    class AskIn(BaseModel):
        question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
        actor: str = Field("anonymous", max_length=100)
        top_k: int = Field(3, ge=1, le=10)

    class ApprovalIn(BaseModel):
        requester: str = Field(min_length=1, max_length=100)
        title: str = Field(min_length=1, max_length=200)
        detail: str = Field("", max_length=MAX_TEXT_FIELD)

    class DecisionIn(BaseModel):
        approver: str = Field(min_length=1, max_length=100)
        approve: bool
        note: str = Field("", max_length=MAX_TEXT_FIELD)

    @app.post("/v1/docs")
    def add_docs(body: DocIn, response: Response, t: str = Depends(tenant)):
        _mark_auth_mode(response)
        chunks = ingest_markdown(body.text, doc_id=body.doc_id, version=body.version)
        added = ctx.db.add_chunks(t, chunks)
        return {"added": added, "parsed": len(chunks),
                "skipped_duplicates": len(chunks) - added}

    @app.post("/v1/ask")
    def ask(body: AskIn, response: Response, t: str = Depends(tenant)):
        _mark_auth_mode(response)
        before = ctx.audit_seq(t)
        ans = ctx.qa_agent(t).ask(body.question, actor=body.actor, top_k=body.top_k)
        ctx.persist_new_audit(t, before)
        return ans.as_dict()

    @app.post("/v1/approvals", status_code=201)
    def create_approval(body: ApprovalIn, response: Response, t: str = Depends(tenant)):
        """申請を起票して承認待ちにする. **自動決裁はしない**(決裁は別エンドポイント)."""
        _mark_auth_mode(response)
        st = ctx.state(t)
        before = ctx.audit_seq(t)
        route = ctx.policy.route_text(f"{body.title} {body.detail}")
        try:
            req = st.approvals.create(body.requester, body.title, body.detail,
                                      required_approver=route.required_approver,
                                      amount=route.amount,
                                      requires_manual_review=route.requires_manual_review)
            st.approvals.submit(req.id)
        except ApprovalError as exc:
            raise HTTPException(400, str(exc)) from exc
        ctx.db.save_approval(t, req.id, req.requester, req.title, req.detail,
                             approver="", status=req.status,
                             required_approver=route.required_approver,
                             amount=route.amount,
                             requires_manual_review=route.requires_manual_review)
        ctx.persist_new_audit(t, before)
        return {"req_id": req.id, "required_approver": route.required_approver,
                "reason": route.reason, "amount": route.amount,
                "requires_manual_review": route.requires_manual_review,
                "status": req.status, "rule_ref": route.rule_ref}

    @app.post("/v1/approvals/{req_id}/decide")
    def decide(req_id: str, body: DecisionIn, response: Response, t: str = Depends(tenant)):
        _mark_auth_mode(response)
        st = ctx.state(t)
        before = ctx.audit_seq(t)
        try:
            req = st.approvals.decide(req_id, approver=body.approver,
                                      approve=body.approve, note=body.note)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ApprovalError as exc:
            raise HTTPException(409, str(exc)) from exc
        ctx.db.update_approval(t, req_id, req.status, approver=body.approver)
        ctx.persist_new_audit(t, before)
        return req.as_dict()

    @app.get("/v1/approvals")
    def list_approvals(response: Response, t: str = Depends(tenant),
                       status: str = Query("", max_length=20),
                       limit: int = Query(100, ge=1, le=1000),
                       offset: int = Query(0, ge=0)):
        _mark_auth_mode(response)
        return {"items": ctx.db.list_approvals(t, status=status, limit=limit, offset=offset)}

    @app.get("/v1/audit")
    def audit(response: Response, t: str = Depends(tenant),
              limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0)):
        _mark_auth_mode(response)
        return {"entries": ctx.db.list_audit(t, limit=limit, offset=offset),
                "chain_valid": ctx.state(t).audit.verify()}

    @app.get("/v1/report", response_class=HTMLResponse)
    def report(response: Response, t: str = Depends(tenant)):
        _mark_auth_mode(response)
        return build_html_report(ctx.db.list_approvals(t, limit=1000), tenant_id=t)

    class ChatIn(BaseModel):
        message: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
        actor: str = Field("anonymous", max_length=100)
        session_id: Optional[str] = Field(None, max_length=64)

    @app.post("/v1/chat")
    def chat(body: ChatIn, response: Response, t: str = Depends(tenant)):
        """会話エンドポイント. 申請意図なら承認ルーティングを提示、そうでなければ引用必須QA."""
        _mark_auth_mode(response)
        st = ctx.state(t)
        try:
            session = (ctx.sessions.get(body.session_id) if body.session_id
                       else ctx.sessions.create(body.actor))
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        session.add("user", body.message)

        intent = classify_intent(body.message)
        if intent.is_request:
            route = ctx.policy.route_text(body.message)
            reply = (f"承認申請として受け付け可能です。{route.reason}"
                     f"（承認者: {route.required_approver}）")
            session.add("assistant", reply)
            before = ctx.audit_seq(t)
            st.audit.record(body.actor, "chat.approval_suggested",
                            {"message": body.message, "amount": route.amount,
                             "required_approver": route.required_approver})
            ctx.persist_new_audit(t, before)
            return {"session_id": session.id, "type": "approval_suggestion",
                    "intent_reason": intent.reason, **route.as_dict(), "text": reply}

        before = ctx.audit_seq(t)
        ans = ctx.qa_agent(t).ask(body.message, actor=body.actor)
        ctx.persist_new_audit(t, before)
        session.add("assistant", ans.text)
        return {"session_id": session.id, "type": "answer",
                "intent_reason": intent.reason, **ans.as_dict()}

    @app.get("/healthz")
    def healthz():
        return {"status": "ok", "auth_enabled": ctx.auth_enabled,
                "version": app.version}

    return app


def _build_default_app():
    """既定アプリ. 失敗は握り潰さず、原因を明示して落とす(FastAPI 未導入時のみ None)."""
    try:
        import fastapi  # noqa: F401
    except ImportError:
        logger.warning("FastAPI 未インストールのため service.api:app は生成されません "
                       "(`pip install -r requirements.txt`)")
        return None
    return create_app()


app = _build_default_app()
