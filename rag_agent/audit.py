"""監査ログ(差別化). 全ての Q&A・承認操作を追記専用で記録する.

コンプライアンス用途では「後から書き換えられないこと」が価値の中心なので、
単なる list への append ではなく次を備える。

  - seq(連番) と prev_hash / hash による **ハッシュチェーン**(改ざん検知)
  - verify() による整合性検証
  - entries は防御的コピーを返す(外部からの書き換えを防ぐ)
  - 任意の JSONL ファイルシンク(追記専用オープン + flush)

注意: ハッシュチェーンは「気付ける」ための仕組みであり、
書き込み権限を持つ者による全体再計算までは防げない(WORM ストレージ併用が必要)。
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import threading
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Dict, List, Optional

GENESIS_HASH = "0" * 64


@dataclass(frozen=True)
class AuditEntry:
    seq: int
    ts: str
    actor: str
    action: str            # 例: qa.answered / qa.refused / approval.submitted
    detail: Dict
    prev_hash: str = GENESIS_HASH
    hash: str = ""

    def as_dict(self) -> Dict:
        return copy.deepcopy(asdict(self))

    def payload(self) -> str:
        return json.dumps(
            {"seq": self.seq, "ts": self.ts, "actor": self.actor,
             "action": self.action, "detail": self.detail, "prev_hash": self.prev_hash},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)

    def compute_hash(self) -> str:
        return hashlib.sha256(self.payload().encode("utf-8")).hexdigest()


class AuditLog:
    def __init__(self, now_fn=None, sink_path: Optional[str] = None) -> None:
        self._entries: List[AuditEntry] = []
        self._now = now_fn or (lambda: datetime.now(timezone.utc).isoformat())
        self._lock = threading.Lock()
        self._sink_path = sink_path
        if sink_path:
            os.makedirs(os.path.dirname(os.path.abspath(sink_path)) or ".", exist_ok=True)

    def record(self, actor: str, action: str, detail: Optional[Dict] = None) -> AuditEntry:
        with self._lock:
            prev = self._entries[-1].hash if self._entries else GENESIS_HASH
            entry = AuditEntry(seq=len(self._entries) + 1, ts=self._now(),
                               actor=actor or "unknown", action=action,
                               detail=copy.deepcopy(detail or {}), prev_hash=prev)
            entry = AuditEntry(**{**asdict(entry), "hash": entry.compute_hash()})
            self._entries.append(entry)
            self._append_sink(entry)
            return entry

    def _append_sink(self, entry: AuditEntry) -> None:
        if not self._sink_path:
            return
        with open(self._sink_path, "a", encoding="utf-8") as f:   # 追記専用
            f.write(json.dumps(entry.as_dict(), ensure_ascii=False) + "\n")
            f.flush()

    @property
    def entries(self) -> List[AuditEntry]:
        with self._lock:
            return list(self._entries)

    def filter(self, action: str = "", actor: str = "") -> List[AuditEntry]:
        return [e for e in self.entries
                if (not action or e.action == action) and (not actor or e.actor == actor)]

    def verify(self) -> bool:
        """ハッシュチェーンの整合性を検証する(改ざん・欠落の検知)."""
        prev = GENESIS_HASH
        for i, e in enumerate(self.entries, start=1):
            if e.seq != i or e.prev_hash != prev:
                return False
            if e.compute_hash() != e.hash:
                return False
            prev = e.hash
        return True

    def to_jsonl(self) -> str:
        return "\n".join(json.dumps(e.as_dict(), ensure_ascii=False) for e in self.entries)

    def __len__(self) -> int:
        return len(self._entries)
