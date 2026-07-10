"""監査ログ(差別化). 全ての Q&A・承認操作を追記専用で記録する."""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Dict, List, Optional


@dataclass
class AuditEntry:
    ts: str
    actor: str
    action: str            # 例: qa.answered / qa.refused / approval.submitted
    detail: Dict

    def as_dict(self):
        return asdict(self)


class AuditLog:
    def __init__(self, now_fn=None) -> None:
        self._entries: List[AuditEntry] = []
        self._now = now_fn or (lambda: datetime.now(timezone.utc).isoformat())

    def record(self, actor: str, action: str, detail: Optional[Dict] = None) -> AuditEntry:
        entry = AuditEntry(ts=self._now(), actor=actor, action=action, detail=detail or {})
        self._entries.append(entry)
        return entry

    @property
    def entries(self) -> List[AuditEntry]:
        return list(self._entries)

    def filter(self, action: str) -> List[AuditEntry]:
        return [e for e in self._entries if e.action == action]

    def to_jsonl(self) -> str:
        return "\n".join(json.dumps(e.as_dict(), ensure_ascii=False) for e in self._entries)
