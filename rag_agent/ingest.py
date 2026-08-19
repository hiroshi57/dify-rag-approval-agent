"""ドキュメント取込. Markdown(規程/FAQ)をセクション単位のチャンクに分解する.

セクション境界:
  - 「第N条(…)」形式(規程) — 見出しらしい行(短い行)だけを境界とする
  - Markdown 見出し(#, ##, ###)
  - ``` フェンス内は分割しない

各チャンクに出典(doc_id / doc_title / section_id / version)を付与し、
後段の「引用必須回答」と「陳腐化検知」を支える。

PDF は pypdf があれば取込む。無い場合は **黙って捨てず** 警告を出す
(silent data loss を避ける。strict=True なら例外)。
"""
from __future__ import annotations

import logging
import os
import re
from typing import List, Optional

from .store import DocChunk

logger = logging.getLogger(__name__)

# 「第3条(締め日)」「第12条の2」などに対応
_ARTICLE_RE = re.compile(
    r"^(第[0-9０-９一二三四五六七八九十百千]+条(?:の[0-9０-９一二三四五六七八九十]+)?)"
    r"\s*[（(]?([^）)\n]*)[）)]?"
)
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
_FENCE_RE = re.compile(r"^(```|~~~)")

# 「第4条に基づき〜」のような本文中の参照を見出しと誤認しないための上限
_HEADING_MAX_LEN = 40

TEXT_EXTENSIONS = (".md", ".markdown", ".txt")


def _is_article_heading(line: str, m: re.Match) -> bool:
    """条番号で始まる行が「見出し」か「本文中の参照」かを判定する."""
    if len(line) <= _HEADING_MAX_LEN:
        return True
    # 長い行でも「第N条（見出し）」直後で終わっていれば見出し扱い
    return m.end() >= len(line)


def ingest_markdown(text: str, doc_id: str, version: str = "",
                    doc_title: str = "") -> List[DocChunk]:
    """Markdown 文字列をセクションチャンクへ分解する.

    doc_title 未指定時は最初の H1 を文書名として採用する(引用表示に使う)。
    """
    lines = text.splitlines()
    chunks: List[DocChunk] = []

    title_from_h1 = ""
    for line in lines:
        m = _HEADING_RE.match(line.strip())
        if m and len(m.group(1)) == 1:
            title_from_h1 = m.group(2).strip()
            break
    resolved_doc_title = doc_title or title_from_h1 or doc_id

    cur_section = "前文"
    cur_title = ""
    buf: List[str] = []
    in_fence = False

    def flush() -> None:
        body = "\n".join(buf).strip()
        if body:
            chunks.append(DocChunk(doc_id=doc_id, section_id=cur_section,
                                   title=cur_title or cur_section, text=body,
                                   doc_title=resolved_doc_title, version=version))

    for raw in lines:
        line = raw.strip()
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            buf.append(raw)
            continue
        if in_fence:
            buf.append(raw)
            continue

        m_art = _ARTICLE_RE.match(line)
        m_head = _HEADING_RE.match(line)
        if m_art and _is_article_heading(line, m_art):
            flush()
            buf = []
            cur_section = m_art.group(1)
            cur_title = m_art.group(2).strip() or m_art.group(1)
            buf.append(line)                       # 条見出しも本文に残す(検索対象)
        elif m_head:
            flush()
            buf = []
            heading = m_head.group(2).strip()
            if len(m_head.group(1)) == 1 and heading == resolved_doc_title:
                # 文書タイトル(H1)はセクションにしない
                cur_section, cur_title = "前文", resolved_doc_title
                continue
            cur_section = heading
            cur_title = heading
            buf.append(heading)                    # 見出し語も本文に残す(検索対象)
        else:
            buf.append(raw)
    flush()
    return chunks


def ingest_markdown_file(path: str, doc_id: str = "", version: str = "") -> List[DocChunk]:
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    return ingest_markdown(text, doc_id or os.path.splitext(os.path.basename(path))[0],
                           version=version)


def ingest_pdf_file(path: str, doc_id: str = "", version: str = "",
                    strict: bool = False) -> List[DocChunk]:
    """PDF 取込(任意). pypdf 未インストール時は警告を出して空を返す.

    strict=True の場合は例外を送出する(取込漏れを検知したいバッチ用)。
    """
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError as exc:       # pragma: no cover - 環境依存
        msg = (f"pypdf 未インストールのため PDF を取込めません: {path} "
               f"(`pip install pypdf` で有効化)")
        if strict:
            raise RuntimeError(msg) from exc
        logger.warning(msg)
        return []
    reader = PdfReader(path)
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    if not text.strip():
        logger.warning("PDF からテキストを抽出できませんでした(画像PDFの可能性): %s", path)
        return []
    return ingest_markdown(text, doc_id or os.path.splitext(os.path.basename(path))[0],
                           version=version)


def ingest_dir(docs_dir: str, recursive: bool = True, version: str = "",
               strict: bool = False) -> List[DocChunk]:
    """ディレクトリ配下の規程を取込む. 取込対象外・失敗は警告として可視化する."""
    chunks: List[DocChunk] = []
    skipped: List[str] = []

    def _walk(directory: str) -> List[str]:
        found: List[str] = []
        for name in sorted(os.listdir(directory)):
            path = os.path.join(directory, name)
            if os.path.isdir(path):
                if recursive and not name.startswith("."):
                    found.extend(_walk(path))
                continue
            found.append(path)
        return found

    for path in _walk(docs_dir):
        lower = path.lower()
        try:
            if lower.endswith(TEXT_EXTENSIONS):
                chunks.extend(ingest_markdown_file(path, version=version))
            elif lower.endswith(".pdf"):
                chunks.extend(ingest_pdf_file(path, version=version, strict=strict))
            else:
                skipped.append(path)
        except OSError as exc:       # 読めないファイルで全体を止めない
            if strict:
                raise
            logger.warning("取込に失敗しました: %s (%s)", path, exc)
    if skipped:
        logger.info("取込対象外としてスキップ: %s", ", ".join(os.path.basename(p) for p in skipped))
    return chunks


def resolve_version(chunks: List[DocChunk], version: Optional[str]) -> List[DocChunk]:
    """既存チャンク群に版を後付けする(取込後にバージョンが判明した場合用)."""
    if not version:
        return chunks
    return [c.with_version(version) for c in chunks]
