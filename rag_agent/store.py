"""文書チャンクのストア. 各チャンクは引用に使う出典メタデータを必ず持つ."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class DocChunk:
    doc_id: str          # 例: "経費精算規程"
    section_id: str      # 例: "第3条" / "## 締め日"
    title: str           # セクション見出し
    text: str            # 本文

    @property
    def citation(self) -> str:
        return f"{self.doc_id} {self.section_id}".strip()


class DocumentStore:
    def __init__(self) -> None:
        self._chunks: List[DocChunk] = []

    def add(self, chunk: DocChunk) -> None:
        self._chunks.append(chunk)

    def extend(self, chunks: List[DocChunk]) -> None:
        self._chunks.extend(chunks)

    @property
    def chunks(self) -> List[DocChunk]:
        return list(self._chunks)

    def __len__(self) -> int:
        return len(self._chunks)
