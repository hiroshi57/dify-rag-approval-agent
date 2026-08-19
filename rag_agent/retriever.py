"""検索. 外部依存なしの idf 重み付き語彙検索.

旧実装の問題(本リポの回帰テストで固定した既知の欠陥):
  - スコアが「クエリ語の被覆率」だけで、語の情報量(idf)を見ていなかった。
    その結果、助詞由来のノイズ語が一致するだけでスコアが立ち、
    規程に書かれていない質問(例: 「在宅勤務中に副業してよいか」)にも
    無関係な条文を"それらしく"返してしまっていた。
  - 語彙外(コーパスに存在しない=df 0)の内容語を無視していたため、
    「答えられないこと」を検知できなかった。

本実装では
  1. 内容語トークン(textnorm.content_tokens)に idf 重みを与えてスコア化
  2. クエリ中の **語彙外語の重み比率** (out_of_scope_ratio) を算出
     -> 回答可能性のゲート(agent.py)がこれを使って「答えない」判断をする
本番で Dify 内蔵ベクトルDBに置換する場合も、retrieve() が返す
RetrievalHit / QueryAnalysis の形を保てば後段はそのまま動く。
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Sequence

from .store import DocChunk, DocumentStore
from .textnorm import content_tokens, tokenize  # noqa: F401  (tokenize は後方互換の再輸出)


@dataclass
class RetrievalHit:
    chunk: DocChunk
    score: float                                   # 0..1 のクエリ被覆率(idf 重み付き)
    matched_terms: List[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"citation": self.chunk.citation, "score": round(self.score, 3),
                "matched_terms": self.matched_terms}


@dataclass
class QueryAnalysis:
    """クエリ側の分析結果. 「答えられるか」の判断材料."""
    tokens: List[str]
    out_of_scope_terms: List[str]                  # コーパスに一度も現れない内容語
    out_of_scope_ratio: float                      # 語彙外語が占める情報量の比率 0..1

    def as_dict(self) -> dict:
        return {"out_of_scope_terms": self.out_of_scope_terms,
                "out_of_scope_ratio": round(self.out_of_scope_ratio, 3)}


class Retriever:
    """idf 重み付きの語彙検索器.

    インデックスは初期化時に一度だけ構築する(リクエスト毎の再構築は行わない)。
    """

    def __init__(self, store: DocumentStore) -> None:
        self.store = store
        chunks = store.chunks
        self._chunks: List[DocChunk] = chunks
        self._doc_tokens: List[frozenset] = []
        df: Counter = Counter()
        for c in chunks:
            toks = frozenset(content_tokens(f"{c.display_doc} {c.title}\n{c.text}"))
            self._doc_tokens.append(toks)
            df.update(toks)
        self._df: Dict[str, int] = dict(df)
        self._n = max(len(chunks), 1)

    # --- 重み ---
    def idf(self, term: str) -> float:
        """BM25 系の idf. df=0(語彙外)は最大重みになる."""
        df = self._df.get(term, 0)
        return math.log(1.0 + (self._n - df + 0.5) / (df + 0.5))

    def vocabulary_size(self) -> int:
        return len(self._df)

    # --- 分析 ---
    def analyze(self, query: str) -> QueryAnalysis:
        tokens = list(dict.fromkeys(content_tokens(query)))  # 重複除去・順序保持
        if not tokens:
            return QueryAnalysis(tokens=[], out_of_scope_terms=[], out_of_scope_ratio=1.0)
        weights = {t: self.idf(t) for t in tokens}
        total = sum(weights.values()) or 1.0
        oos = [t for t in tokens if self._df.get(t, 0) == 0]
        oos_weight = sum(weights[t] for t in oos)
        return QueryAnalysis(tokens=tokens, out_of_scope_terms=oos,
                             out_of_scope_ratio=oos_weight / total)

    # --- 検索 ---
    def retrieve(self, query: str, top_k: int = 3) -> List[RetrievalHit]:
        tokens = list(dict.fromkeys(content_tokens(query)))
        if not tokens or not self._chunks:
            return []
        weights = {t: self.idf(t) for t in tokens}
        total = sum(weights.values()) or 1.0

        hits: List[RetrievalHit] = []
        for chunk, doc_tokens in zip(self._chunks, self._doc_tokens):
            matched = [t for t in tokens if t in doc_tokens]
            if not matched:
                continue
            score = sum(weights[t] for t in matched) / total
            hits.append(RetrievalHit(chunk=chunk, score=score, matched_terms=matched))
        # 同点時は本文が短い(=より限定的な)チャンクを優先し、決定的な順序にする
        hits.sort(key=lambda h: (-h.score, len(h.chunk.text), h.chunk.citation))
        return hits[:max(top_k, 0)]

    def search(self, query: str, top_k: int = 3) -> Sequence[RetrievalHit]:
        """retrieve のエイリアス(ベクトルDB置換時の呼び出し名互換用)."""
        return self.retrieve(query, top_k=top_k)
