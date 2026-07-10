"""Q&A チャットボット. 差別化: 引用が取れない質問には答えない(ハルシネーション抑止).

回答は必ず出典(規程名+条番号)を伴う。関連スコアが閾値未満なら
「該当する規程が見つかりません」と返し、根拠のない回答を生成しない。
LLM(Claude)接続点は _compose にあり、未接続時は抽出型のルールベースで動く。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .audit import AuditLog
from .retriever import Retriever, RetrievalHit


@dataclass
class Citation:
    doc_id: str
    section_id: str
    title: str


@dataclass
class Answer:
    answered: bool
    text: str
    citations: List[Citation] = field(default_factory=list)

    def as_dict(self):
        return {
            "answered": self.answered,
            "text": self.text,
            "citations": [c.__dict__ for c in self.citations],
        }


REFUSAL = "該当する社内規程・FAQが見つかりませんでした。根拠が確認できないため回答を差し控えます。"


class QAAgent:
    def __init__(self, retriever: Retriever, audit: Optional[AuditLog] = None,
                 min_score: float = 0.15) -> None:
        self.retriever = retriever
        self.audit = audit or AuditLog()
        self.min_score = min_score

    def _compose(self, question: str, hits: List[RetrievalHit]) -> str:
        # LLM 未接続時の抽出型フォールバック: 最上位チャンクの本文を根拠として提示
        top = hits[0].chunk
        body = top.text.replace("\n", " ").strip()
        cite = "、".join(f"「{h.chunk.citation}」" for h in hits)
        return f"{body}（出典: {cite}）"

    def ask(self, question: str, actor: str = "anonymous") -> Answer:
        hits = self.retriever.retrieve(question, top_k=3)
        relevant = [h for h in hits if h.score >= self.min_score]
        if not relevant:
            ans = Answer(answered=False, text=REFUSAL, citations=[])
            self.audit.record(actor, "qa.refused", {"question": question,
                                                     "top_score": hits[0].score if hits else 0})
            return ans
        citations = [Citation(h.chunk.doc_id, h.chunk.section_id, h.chunk.title) for h in relevant]
        ans = Answer(answered=True, text=self._compose(question, relevant), citations=citations)
        self.audit.record(actor, "qa.answered", {
            "question": question,
            "citations": [c.section_id for c in citations],
            "top_score": round(relevant[0].score, 3),
        })
        return ans
