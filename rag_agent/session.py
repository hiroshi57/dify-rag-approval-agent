"""マルチターン会話セッション. 会話IDごとに履歴を保持する."""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class Turn:
    role: str        # user / assistant
    text: str


@dataclass
class Session:
    id: str
    actor: str
    history: List[Turn] = field(default_factory=list)

    def add(self, role: str, text: str) -> None:
        self.history.append(Turn(role, text))

    @property
    def turn_count(self) -> int:
        return len(self.history)


class SessionStore:
    def __init__(self) -> None:
        self._sessions: Dict[str, Session] = {}
        self._seq = itertools.count(1)

    def create(self, actor: str) -> Session:
        sid = f"S-{next(self._seq):04d}"
        s = Session(id=sid, actor=actor)
        self._sessions[sid] = s
        return s

    def get(self, sid: str) -> Session:
        if sid not in self._sessions:
            raise KeyError(f"セッションが見つかりません: {sid}")
        return self._sessions[sid]
