"""マルチターン会話セッション. 会話IDごとに履歴を保持する.

長時間稼働のサービスで無制限に溜め込むとメモリリークになるため、
セッション数と履歴長に上限を設け、LRU で退避する。
"""
from __future__ import annotations

import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Turn:
    role: str        # user / assistant
    text: str
    at: str = field(default_factory=_now)


@dataclass
class Session:
    id: str
    actor: str
    history: List[Turn] = field(default_factory=list)
    max_turns: int = 50

    def add(self, role: str, text: str) -> None:
        if role not in ("user", "assistant", "system"):
            raise ValueError(f"未知の role: {role}")
        self.history.append(Turn(role, text))
        if len(self.history) > self.max_turns:
            del self.history[: len(self.history) - self.max_turns]

    @property
    def turn_count(self) -> int:
        return len(self.history)


class SessionStore:
    def __init__(self, max_sessions: int = 1000, max_turns: int = 50) -> None:
        self._sessions: "OrderedDict[str, Session]" = OrderedDict()
        self._lock = threading.Lock()
        self.max_sessions = max_sessions
        self.max_turns = max_turns

    def create(self, actor: str) -> Session:
        sid = f"S-{uuid.uuid4().hex[:10].upper()}"
        s = Session(id=sid, actor=actor, max_turns=self.max_turns)
        with self._lock:
            self._sessions[sid] = s
            while len(self._sessions) > self.max_sessions:
                self._sessions.popitem(last=False)     # 最も古いものから退避
        return s

    def get(self, sid: str) -> Session:
        with self._lock:
            if sid not in self._sessions:
                raise KeyError(f"セッションが見つかりません: {sid}")
            self._sessions.move_to_end(sid)
            return self._sessions[sid]

    def __len__(self) -> int:
        return len(self._sessions)
