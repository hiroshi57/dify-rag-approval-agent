"""承認申請フロー. 会話から申請意図を検知し、承認リクエストを起票・状態管理する."""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .audit import AuditLog
from .integrations.slack import SlackNotifier

_INTENT_MARKERS = ("申請", "承認", "稟議", "決裁", "申し込みたい", "申込みたい", "経費精算したい", "有給")

VALID = {"draft", "submitted", "approved", "rejected"}


def detect_approval_intent(text: str) -> bool:
    return any(m in text for m in _INTENT_MARKERS)


@dataclass
class ApprovalRequest:
    id: str
    requester: str
    title: str
    detail: str
    status: str = "draft"

    def as_dict(self):
        return {"id": self.id, "requester": self.requester, "title": self.title,
                "detail": self.detail, "status": self.status}


class ApprovalStore:
    def __init__(self, notifier: Optional[SlackNotifier] = None,
                 audit: Optional[AuditLog] = None) -> None:
        self._items: Dict[str, ApprovalRequest] = {}
        self._seq = itertools.count(1)
        self.notifier = notifier or SlackNotifier()
        self.audit = audit or AuditLog()

    def create(self, requester: str, title: str, detail: str) -> ApprovalRequest:
        rid = f"REQ-{next(self._seq):04d}"
        req = ApprovalRequest(id=rid, requester=requester, title=title, detail=detail)
        self._items[rid] = req
        self.audit.record(requester, "approval.created", {"id": rid, "title": title})
        return req

    def submit(self, rid: str) -> ApprovalRequest:
        req = self._require(rid)
        if req.status != "draft":
            raise ValueError(f"{rid} は draft ではないため提出できません(現在: {req.status})")
        req.status = "submitted"
        self.audit.record(req.requester, "approval.submitted", {"id": rid})
        self.notifier.notify(
            f"[承認申請] {req.id}: {req.title}\n申請者: {req.requester}\n内容: {req.detail}"
        )
        return req

    def decide(self, rid: str, approver: str, approve: bool) -> ApprovalRequest:
        req = self._require(rid)
        if req.status != "submitted":
            raise ValueError(f"{rid} は submitted ではないため決裁できません(現在: {req.status})")
        req.status = "approved" if approve else "rejected"
        self.audit.record(approver, f"approval.{req.status}", {"id": rid})
        self.notifier.notify(f"[承認結果] {req.id}: {req.status} (決裁者: {approver})")
        return req

    def get(self, rid: str) -> ApprovalRequest:
        return self._require(rid)

    def _require(self, rid: str) -> ApprovalRequest:
        if rid not in self._items:
            raise KeyError(f"承認申請が見つかりません: {rid}")
        return self._items[rid]
