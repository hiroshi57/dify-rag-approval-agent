"""検索. 外部依存なしのトークン重複スコアで関連チャンクを返す.

日本語対応のため、ASCII 語 + CJK 文字bigram でトークン化する。
本番では Dify 内蔵ベクトルDBに置換する前提(インターフェースは retrieve に集約)。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Tuple

from .store import DocChunk, DocumentStore

_ASCII_RE = re.compile(r"[a-zA-Z0-9]+")
_CJK_RE = re.compile(r"[぀-ヿ一-鿿々〆ぁ-んァ-ヶ]+")


def tokenize(text: str) -> List[str]:
    text = text.lower()
    tokens: List[str] = [w for w in _ASCII_RE.findall(text)]
    for run in _CJK_RE.findall(text):
        if len(run) == 1:
            tokens.append(run)
        else:
            tokens.extend(run[i:i + 2] for i in range(len(run) - 1))  # 文字bigram
    return tokens


@dataclass
class RetrievalHit:
    chunk: DocChunk
    score: float


class Retriever:
    def __init__(self, store: DocumentStore) -> None:
        self.store = store
        self._index = [(c, set(tokenize(c.title + "\n" + c.text))) for c in store.chunks]

    def retrieve(self, query: str, top_k: int = 3) -> List[RetrievalHit]:
        q_tokens = tokenize(query)
        if not q_tokens:
            return []
        q_set = set(q_tokens)
        hits: List[RetrievalHit] = []
        for chunk, tokens in self._index:
            if not tokens:
                continue
            overlap = len(q_set & tokens)
            if overlap == 0:
                continue
            score = overlap / len(q_set)   # クエリ被覆率で正規化(0-1)
            hits.append(RetrievalHit(chunk=chunk, score=score))
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:top_k]
