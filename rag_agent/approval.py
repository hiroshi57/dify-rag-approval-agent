"""承認申請フロー. 会話から申請意図を検知し、承認リクエストを起票・状態管理する.

設計上の要点:
  - **質問と申請意図を区別する**。「有給休暇はどう申請しますか？」は Q&A であって
    申請起票ではない。旧実装は "有給" や "承認" の部分一致だけで意図と判定していたため、
    規程を尋ねただけの発話が承認フローに流れていた。
  - **職務分離(SoD)**: 申請者自身は決裁できない。
  - **通知失敗で状態を壊さない**: 状態遷移を確定してから通知し、
    通知の失敗は監査ログに残すが遷移は巻き戻さない(二重申請を誘発しないため)。
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from .audit import AuditLog
from .integrations.slack import SlackNotifier

# 申請の意思を示す表現(動詞まで含める)
_REQUEST_PATTERNS = (
    "申請したい", "申請します", "申請お願い", "申請をお願い", "申請させて", "申請します",
    "起票", "稟議を出", "稟議申請", "稟議にかけ", "決裁をお願い", "決裁依頼",
    "承認をお願い", "承認依頼", "精算したい", "精算します", "購入したい", "購入申請",
    "申し込みたい", "申込みたい", "取得したい", "提出します", "提出したい",
)
# 「〜を〜したい」型の汎用検知に使う名詞
_REQUEST_NOUNS = ("申請", "精算", "承認", "稟議", "決裁", "購入", "取得", "出張", "経費")
_DESIRE_SUFFIX = ("したい", "しますので", "します。", "お願いします", "願います")
# 質問である手掛かり(これがあれば申請意図とはみなさない)
_QUESTION_MARKERS = ("？", "?", "ですか", "でしょうか", "教えて", "どう", "いつ", "どこ",
                     "だれ", "誰", "何日", "何が", "何を", "方法は", "ますか", "可能か")

VALID_STATUSES = ("draft", "submitted", "approved", "rejected", "cancelled")
# 許可された遷移のみを定義(表に無い遷移は例外)
_TRANSITIONS = {
    ("draft", "submitted"),
    ("draft", "cancelled"),
    ("submitted", "approved"),
    ("submitted", "rejected"),
    ("submitted", "cancelled"),
}


@dataclass
class IntentResult:
    is_request: bool
    reason: str

    def __bool__(self) -> bool:      # 後方互換(bool として扱える)
        return self.is_request


def classify_intent(text: str) -> IntentResult:
    text = (text or "").strip()
    if not text:
        return IntentResult(False, "空文字")
    if any(q in text for q in _QUESTION_MARKERS):
        return IntentResult(False, "質問形のため Q&A として扱う")
    for p in _REQUEST_PATTERNS:
        if p in text:
            return IntentResult(True, f"申請表現を検出: {p}")
    if any(n in text for n in _REQUEST_NOUNS) and any(s in text for s in _DESIRE_SUFFIX):
        return IntentResult(True, "「〜したい/お願いします」型の申請表現を検出")
    return IntentResult(False, "申請表現なし")


def detect_approval_intent(text: str) -> bool:
    """後方互換 API. 詳細が必要なら classify_intent を使う."""
    return classify_intent(text).is_request


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ApprovalRequest:
    id: str
    requester: str
    title: str
    detail: str
    status: str = "draft"
    required_approver: str = ""
    amount: Optional[int] = None
    requires_manual_review: bool = False
    decided_by: str = ""
    decision_note: str = ""
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    history: List[Dict] = field(default_factory=list)

    def as_dict(self) -> Dict:
        return {"id": self.id, "requester": self.requester, "title": self.title,
                "detail": self.detail, "status": self.status,
                "required_approver": self.required_approver, "amount": self.amount,
                "requires_manual_review": self.requires_manual_review,
                "decided_by": self.decided_by, "decision_note": self.decision_note,
                "created_at": self.created_at, "updated_at": self.updated_at,
                "history": list(self.history)}


class ApprovalError(ValueError):
    """承認フローの規約違反(遷移不正・職務分離違反など)."""


class ApprovalStore:
    def __init__(self, notifier: Optional[SlackNotifier] = None,
                 audit: Optional[AuditLog] = None,
                 id_factory: Optional[Callable[[], str]] = None) -> None:
        self._items: Dict[str, ApprovalRequest] = {}
        # NOTE: `x or Default()` は使わない。AuditLog は __len__ を持ち、
        # 空ログが falsy になるため「渡した監査ログが黙って捨てられる」事故になる。
        self.notifier = notifier if notifier is not None else SlackNotifier()
        self.audit = audit if audit is not None else AuditLog()
        self._id_factory = id_factory or (lambda: f"REQ-{uuid.uuid4().hex[:10].upper()}")

    # --- 内部 ---
    def _require(self, rid: str) -> ApprovalRequest:
        if rid not in self._items:
            raise KeyError(f"承認申請が見つかりません: {rid}")
        return self._items[rid]

    def _transition(self, req: ApprovalRequest, to: str, actor: str, note: str = "") -> None:
        if to not in VALID_STATUSES:
            raise ApprovalError(f"未知のステータス: {to}")
        if (req.status, to) not in _TRANSITIONS:
            raise ApprovalError(
                f"{req.id} は {req.status} から {to} へ遷移できません")
        req.history.append({"from": req.status, "to": to, "actor": actor,
                            "at": _now(), "note": note})
        req.status = to
        req.updated_at = _now()

    def _notify(self, message: str, context: Dict) -> None:
        """通知失敗で業務状態を壊さない. 失敗は監査ログに残す."""
        try:
            result = self.notifier.notify(message)
        except Exception as exc:                    # noqa: BLE001 - 通知は非致命
            self.audit.record("system", "notify.failed",
                              {**context, "error": f"{type(exc).__name__}: {exc}"})
            return
        if not result.delivered and not result.dry_run:
            self.audit.record("system", "notify.failed", {**context, "error": result.detail})

    # --- 操作 ---
    def create(self, requester: str, title: str, detail: str,
               required_approver: str = "", amount: Optional[int] = None,
               requires_manual_review: bool = False) -> ApprovalRequest:
        if not requester or not requester.strip():
            raise ApprovalError("申請者は必須です")
        if not title or not title.strip():
            raise ApprovalError("件名は必須です")
        rid = self._id_factory()
        req = ApprovalRequest(id=rid, requester=requester.strip(), title=title.strip(),
                              detail=detail, required_approver=required_approver,
                              amount=amount, requires_manual_review=requires_manual_review)
        self._items[rid] = req
        self.audit.record(requester, "approval.created",
                          {"id": rid, "title": title, "amount": amount,
                           "required_approver": required_approver})
        return req

    def submit(self, rid: str, actor: str = "") -> ApprovalRequest:
        req = self._require(rid)
        actor = actor or req.requester
        self._transition(req, "submitted", actor)
        self.audit.record(actor, "approval.submitted",
                          {"id": rid, "required_approver": req.required_approver})
        self._notify(
            f"[承認申請] {req.id}: {req.title}\n申請者: {req.requester}\n"
            f"承認者: {req.required_approver or '未定'}\n内容: {req.detail}",
            {"id": rid, "stage": "submitted"})
        return req

    def decide(self, rid: str, approver: str, approve: bool, note: str = "") -> ApprovalRequest:
        req = self._require(rid)
        if not approver or not approver.strip():
            raise ApprovalError("決裁者は必須です")
        approver = approver.strip()
        if approver == req.requester:
            raise ApprovalError(
                f"職務分離違反: 申請者({req.requester})自身は決裁できません")
        target = "approved" if approve else "rejected"
        self._transition(req, target, approver, note)
        req.decided_by = approver
        req.decision_note = note
        self.audit.record(approver, f"approval.{target}", {"id": rid, "note": note})
        self._notify(f"[承認結果] {req.id}: {target} (決裁者: {approver})",
                     {"id": rid, "stage": target})
        return req

    def cancel(self, rid: str, actor: str, note: str = "") -> ApprovalRequest:
        req = self._require(rid)
        self._transition(req, "cancelled", actor, note)
        self.audit.record(actor, "approval.cancelled", {"id": rid, "note": note})
        return req

    def get(self, rid: str) -> ApprovalRequest:
        return self._require(rid)

    def list(self, status: str = "") -> List[ApprovalRequest]:
        items = list(self._items.values())
        return [r for r in items if not status or r.status == status]


# 「第4条に基づき〜」等の条番号参照を本文から拾うユーティリティ(監査説明用)
_ARTICLE_REF_RE = re.compile(r"第[0-9０-９一二三四五六七八九十百千]+条")


def referenced_articles(text: str) -> List[str]:
    return list(dict.fromkeys(_ARTICLE_REF_RE.findall(text or "")))
