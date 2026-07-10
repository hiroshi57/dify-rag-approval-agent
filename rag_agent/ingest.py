"""ドキュメント取込. Markdown(規程/FAQ)をセクション単位のチャンクに分解する.

セクション境界:
  - 「第N条(…)」形式(規程)
  - Markdown 見出し(#, ##, ###)
各チャンクに出典(doc_id, section_id)を付与し、後段の引用必須回答を支える。
PDF は pypdf があれば取込、無ければスキップ(MVPでは Markdown を主とする)。
"""
from __future__ import annotations

import os
import re
from typing import List

from .store import DocChunk

_ARTICLE_RE = re.compile(r"^(第[0-9０-９一二三四五六七八九十百]+条)\s*[（(]?([^）)\n]*)[）)]?")
_HEADING_RE = re.compile(r"^(#{1,3})\s+(.*)$")


def ingest_markdown(text: str, doc_id: str) -> List[DocChunk]:
    lines = text.splitlines()
    chunks: List[DocChunk] = []
    cur_section = "前文"
    cur_title = ""
    buf: List[str] = []

    def flush():
        body = "\n".join(buf).strip()
        if body:
            chunks.append(DocChunk(doc_id=doc_id, section_id=cur_section,
                                   title=cur_title or cur_section, text=body))

    for line in lines:
        m_art = _ARTICLE_RE.match(line.strip())
        m_head = _HEADING_RE.match(line.strip())
        if m_art:
            flush()
            buf = []
            cur_section = m_art.group(1)
            cur_title = m_art.group(2).strip() or m_art.group(1)
            buf.append(line.strip())
        elif m_head:
            flush()
            buf = []
            cur_section = m_head.group(2).strip()
            cur_title = m_head.group(2).strip()
        else:
            buf.append(line)
    flush()
    return chunks


def ingest_markdown_file(path: str, doc_id: str = "") -> List[DocChunk]:
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    return ingest_markdown(text, doc_id or os.path.splitext(os.path.basename(path))[0])


def ingest_pdf_file(path: str, doc_id: str = "") -> List[DocChunk]:
    """PDF 取込(任意). pypdf 未インストール時は空を返す(MVP では Markdown 優先)."""
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception:
        return []
    reader = PdfReader(path)
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    return ingest_markdown(text, doc_id or os.path.splitext(os.path.basename(path))[0])


def ingest_dir(docs_dir: str) -> List[DocChunk]:
    chunks: List[DocChunk] = []
    for name in sorted(os.listdir(docs_dir)):
        path = os.path.join(docs_dir, name)
        if name.lower().endswith(".md"):
            chunks.extend(ingest_markdown_file(path))
        elif name.lower().endswith(".pdf"):
            chunks.extend(ingest_pdf_file(path))
    return chunks
