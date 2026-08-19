"""Q&A. 差別化: 引用が取れない/答えられない質問には答えない(ハルシネーション抑止).

回答は必ず出典(規程名+条番号)を伴う。回答を出す条件は 2 つで、両方を満たす必要がある。

  (1) 十分に関連する条文がある            -> top score >= min_score
  (2) 質問に「規程に存在しない論点」が混ざりすぎていない
                                          -> out_of_scope_ratio <= max_out_of_scope_ratio

(2) が本実装の要点。語彙一致だけを見ると「在宅勤務中に**副業**してよいか」のような
規程に無い論点でも、"在宅勤務"の条文がヒットして"それらしい"回答が出てしまう。
語彙外語の情報量比率でゲートすることで、この誤答を「答えない」に倒す。

LLM(Claude)接続点は _compose にあり、未接続時は抽出型(条文の逐語引用)で動く。
抽出型である限り本モジュールは文章を創作しない。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .audit import AuditLog
from .retriever import Retriever, RetrievalHit
from .staleness import RegulationRegistry

REFUSAL = "該当する社内規程・FAQが見つかりませんでした。根拠が確認できないため回答を差し控えます。"
REFUSAL_PARTIAL = (
    "ご質問のうち、社内規程に定めのない論点が含まれるため回答を差し控えます"
    "（規程外の事項: {terms}）。管理部門へご確認ください。"
)
STALE_NOTICE = "※引用条文が改定されている可能性があります（要再確認）: {items}"

# 既定の閾値。値の根拠は tests/test_retrieval_eval.py の評価セットで測定している。
DEFAULT_MIN_SCORE = 0.30
DEFAULT_MAX_OOS_RATIO = 0.34


@dataclass
class Citation:
    doc_id: str
    section_id: str
    title: str
    doc_title: str = ""
    version: str = ""
    score: float = 0.0

    @property
    def label(self) -> str:
        base = f"{self.doc_title or self.doc_id} {self.section_id}".strip()
        return f"{base}({self.version})" if self.version else base

    def as_dict(self) -> Dict:
        return {"doc_id": self.doc_id, "section_id": self.section_id, "title": self.title,
                "doc_title": self.doc_title, "version": self.version,
                "score": round(self.score, 3), "label": self.label}


@dataclass
class Answer:
    answered: bool
    text: str
    citations: List[Citation] = field(default_factory=list)
    refusal_reason: str = ""          # no_hit / low_score / out_of_scope / empty_query
    top_score: float = 0.0
    out_of_scope_terms: List[str] = field(default_factory=list)
    stale_citations: List[Dict] = field(default_factory=list)

    def __post_init__(self) -> None:
        # 不変条件: 回答した以上、引用は必ず存在する(構造的に保証する)
        if self.answered and not self.citations:
            raise ValueError("answered=True の Answer は citations を持たねばならない")
        if not self.answered and self.citations:
            raise ValueError("answered=False の Answer は citations を持ってはならない")

    def as_dict(self) -> Dict:
        return {
            "answered": self.answered,
            "text": self.text,
            "citations": [c.as_dict() for c in self.citations],
            "refusal_reason": self.refusal_reason,
            "top_score": round(self.top_score, 3),
            "out_of_scope_terms": self.out_of_scope_terms,
            "stale_citations": self.stale_citations,
        }


class QAAgent:
    def __init__(self, retriever: Retriever, audit: Optional[AuditLog] = None,
                 min_score: float = DEFAULT_MIN_SCORE,
                 max_out_of_scope_ratio: float = DEFAULT_MAX_OOS_RATIO,
                 registry: Optional[RegulationRegistry] = None,
                 max_snippet_chars: int = 400) -> None:
        if not 0.0 <= min_score <= 1.0:
            raise ValueError("min_score は 0..1 で指定してください")
        if not 0.0 <= max_out_of_scope_ratio <= 1.0:
            raise ValueError("max_out_of_scope_ratio は 0..1 で指定してください")
        self.retriever = retriever
        self.audit = audit or AuditLog()
        self.min_score = min_score
        self.max_out_of_scope_ratio = max_out_of_scope_ratio
        self.registry = registry
        self.max_snippet_chars = max_snippet_chars

    # --- 回答生成(LLM 未接続時の抽出型フォールバック) ---
    def _compose(self, question: str, hits: List[RetrievalHit]) -> str:
        parts = []
        for h in hits:
            body = " ".join(h.chunk.text.split())
            if len(body) > self.max_snippet_chars:
                body = body[: self.max_snippet_chars - 1] + "…"
            parts.append(f"{body}（出典: 「{h.chunk.citation}」）")
        return "\n".join(parts)

    def _refuse(self, actor: str, question: str, reason: str, text: str,
                top_score: float, oos_terms: List[str]) -> Answer:
        ans = Answer(answered=False, text=text, citations=[], refusal_reason=reason,
                     top_score=top_score, out_of_scope_terms=oos_terms)
        self.audit.record(actor, "qa.refused", {
            "question": question, "reason": reason,
            "top_score": round(top_score, 3), "out_of_scope_terms": oos_terms,
        })
        return ans

    def _stale_info(self, citations: List[Citation]) -> List[Dict]:
        if self.registry is None:
            return []
        stale: List[Dict] = []
        for c in citations:
            if not c.version:
                continue
            if self.registry.is_stale(c.doc_id, c.section_id, c.version):
                latest = self.registry.latest(c.doc_id)
                stale.append({"doc_id": c.doc_id, "section_id": c.section_id,
                              "cited_version": c.version,
                              "latest_version": latest.version if latest else "?"})
        return stale

    def ask(self, question: str, actor: str = "anonymous", top_k: int = 3) -> Answer:
        question = (question or "").strip()
        if not question:
            return self._refuse(actor, question, "empty_query", REFUSAL, 0.0, [])

        analysis = self.retriever.analyze(question)
        hits = self.retriever.retrieve(question, top_k=top_k)
        top_score = hits[0].score if hits else 0.0

        if not hits:
            return self._refuse(actor, question, "no_hit", REFUSAL, 0.0,
                                analysis.out_of_scope_terms)
        if analysis.out_of_scope_ratio > self.max_out_of_scope_ratio:
            text = REFUSAL_PARTIAL.format(terms="、".join(analysis.out_of_scope_terms[:5]))
            return self._refuse(actor, question, "out_of_scope", text, top_score,
                                analysis.out_of_scope_terms)

        relevant = [h for h in hits if h.score >= self.min_score]
        if not relevant:
            return self._refuse(actor, question, "low_score", REFUSAL, top_score,
                                analysis.out_of_scope_terms)

        citations = [Citation(doc_id=h.chunk.doc_id, section_id=h.chunk.section_id,
                              title=h.chunk.title, doc_title=h.chunk.doc_title,
                              version=h.chunk.version, score=h.score) for h in relevant]
        stale = self._stale_info(citations)
        text = self._compose(question, relevant)
        if stale:
            items = "、".join(f"{s['doc_id']} {s['section_id']}" for s in stale)
            text = f"{text}\n{STALE_NOTICE.format(items=items)}"

        ans = Answer(answered=True, text=text, citations=citations,
                     top_score=top_score, out_of_scope_terms=analysis.out_of_scope_terms,
                     stale_citations=stale)
        self.audit.record(actor, "qa.answered", {
            "question": question,
            "citations": [c.label for c in citations],
            "top_score": round(top_score, 3),
            "stale_citations": stale,
        })
        return ans
