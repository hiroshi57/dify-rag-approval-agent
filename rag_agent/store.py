"""文書チャンクのストア. 各チャンクは引用に使う出典メタデータを必ず持つ."""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterator, List, Optional


@dataclass(frozen=True)
class DocChunk:
    doc_id: str                 # 文書の一意キー(例: "expense_policy")
    section_id: str             # 例: "第3条" / "有給休暇の申請方法"
    title: str                  # セクション見出し
    text: str                   # 本文
    doc_title: str = ""         # 人が読む文書名(例: "経費精算規程"). 空なら doc_id を使う
    version: str = ""           # 規程の版(例: "v2"). 陳腐化検知に使う

    @property
    def display_doc(self) -> str:
        return self.doc_title or self.doc_id

    @property
    def citation(self) -> str:
        """引用表記. 例: 「経費精算規程 第3条(v2)」"""
        base = f"{self.display_doc} {self.section_id}".strip()
        return f"{base}({self.version})" if self.version else base

    def with_version(self, version: str) -> "DocChunk":
        return replace(self, version=version)


class DocumentStore:
    def __init__(self, chunks: Optional[List[DocChunk]] = None) -> None:
        self._chunks: List[DocChunk] = list(chunks or [])

    def add(self, chunk: DocChunk) -> None:
        self._chunks.append(chunk)

    def extend(self, chunks: List[DocChunk]) -> None:
        self._chunks.extend(chunks)

    def clear(self) -> None:
        self._chunks.clear()

    @property
    def chunks(self) -> List[DocChunk]:
        return list(self._chunks)

    def __iter__(self) -> Iterator[DocChunk]:
        return iter(self._chunks)

    def __len__(self) -> int:
        return len(self._chunks)
