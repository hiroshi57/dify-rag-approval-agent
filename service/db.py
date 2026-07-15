"""永続化層(SQLite, 標準ライブラリ). 文書チャンク + 承認申請. テナント分離."""
from __future__ import annotations

import sqlite3
from typing import List, Optional

from rag_agent import DocChunk

SCHEMA = """
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    section_id TEXT NOT NULL,
    title TEXT NOT NULL,
    text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL,
    req_id TEXT NOT NULL,
    requester TEXT NOT NULL,
    title TEXT NOT NULL,
    detail TEXT NOT NULL,
    approver TEXT NOT NULL,
    status TEXT NOT NULL
);
"""


class ServiceDB:
    def __init__(self, path: str = ":memory:") -> None:
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # --- chunks ---
    def add_chunks(self, tenant_id: str, chunks: List[DocChunk]) -> int:
        for c in chunks:
            self.conn.execute(
                "INSERT INTO chunks(tenant_id, doc_id, section_id, title, text) VALUES (?,?,?,?,?)",
                (tenant_id, c.doc_id, c.section_id, c.title, c.text))
        self.conn.commit()
        return len(chunks)

    def get_chunks(self, tenant_id: str) -> List[DocChunk]:
        rows = self.conn.execute(
            "SELECT doc_id, section_id, title, text FROM chunks WHERE tenant_id=?",
            (tenant_id,)).fetchall()
        return [DocChunk(doc_id=r["doc_id"], section_id=r["section_id"],
                         title=r["title"], text=r["text"]) for r in rows]

    # --- approvals ---
    def save_approval(self, tenant_id: str, req_id: str, requester: str, title: str,
                      detail: str, approver: str, status: str) -> None:
        self.conn.execute(
            "INSERT INTO approvals(tenant_id, req_id, requester, title, detail, approver, status) "
            "VALUES (?,?,?,?,?,?,?)",
            (tenant_id, req_id, requester, title, detail, approver, status))
        self.conn.commit()

    def list_approvals(self, tenant_id: str) -> List[dict]:
        rows = self.conn.execute(
            "SELECT req_id, requester, title, detail, approver, status FROM approvals "
            "WHERE tenant_id=?", (tenant_id,)).fetchall()
        return [dict(r) for r in rows]

    def close(self) -> None:
        self.conn.close()
