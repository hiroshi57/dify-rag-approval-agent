"""永続化層(SQLite, 標準ライブラリ). 文書チャンク + 承認申請 + 監査ログ.

テナント分離について(重要な但し書き):
  本層は全クエリに tenant_id を必須とする「行レベルの分離」を提供する。
  これは **認証と組み合わせて初めて意味を持つ**。呼び出し側(API)が
  tenant_id を検証せずクライアント指定のヘッダをそのまま渡すなら、
  分離は成立しない。API 側の認証実装(service/api.py)と対で読むこと。
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
from typing import Dict, List, Optional

from rag_agent import DocChunk

TENANT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    doc_title TEXT NOT NULL DEFAULT '',
    version TEXT NOT NULL DEFAULT '',
    section_id TEXT NOT NULL,
    title TEXT NOT NULL,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_chunks_tenant ON chunks(tenant_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_chunks
    ON chunks(tenant_id, doc_id, version, section_id, title);

CREATE TABLE IF NOT EXISTS approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL,
    req_id TEXT NOT NULL,
    requester TEXT NOT NULL,
    title TEXT NOT NULL,
    detail TEXT NOT NULL,
    approver TEXT NOT NULL DEFAULT '',
    required_approver TEXT NOT NULL DEFAULT '',
    amount INTEGER,
    requires_manual_review INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL CHECK (status IN
        ('draft','submitted','approved','rejected','cancelled')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_approvals_req ON approvals(tenant_id, req_id);
CREATE INDEX IF NOT EXISTS idx_approvals_tenant ON approvals(tenant_id, status);

CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    ts TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    detail TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    hash TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_audit_seq ON audit(tenant_id, seq);
CREATE INDEX IF NOT EXISTS idx_audit_tenant ON audit(tenant_id, id);
"""


def validate_tenant(tenant_id: str) -> str:
    if not tenant_id or not TENANT_RE.match(tenant_id):
        raise ValueError("tenant_id が不正です(英数字と _.- のみ, 1-64文字)")
    return tenant_id


class ServiceDB:
    def __init__(self, path: str = ":memory:") -> None:
        self.path = path
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()      # sqlite3 接続の共有は直列化が必要
        with self._lock:
            if path != ":memory:":
                self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.executescript(SCHEMA)
            self.conn.commit()

    # --- chunks ---
    def add_chunks(self, tenant_id: str, chunks: List[DocChunk]) -> int:
        validate_tenant(tenant_id)
        added = 0
        with self._lock:
            for c in chunks:
                cur = self.conn.execute(
                    "INSERT OR IGNORE INTO chunks"
                    "(tenant_id, doc_id, doc_title, version, section_id, title, text) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (tenant_id, c.doc_id, c.doc_title, c.version, c.section_id,
                     c.title, c.text))
                added += cur.rowcount if cur.rowcount > 0 else 0
            self.conn.commit()
        return added

    def get_chunks(self, tenant_id: str) -> List[DocChunk]:
        validate_tenant(tenant_id)
        with self._lock:
            rows = self.conn.execute(
                "SELECT doc_id, doc_title, version, section_id, title, text "
                "FROM chunks WHERE tenant_id=? ORDER BY id", (tenant_id,)).fetchall()
        return [DocChunk(doc_id=r["doc_id"], section_id=r["section_id"], title=r["title"],
                         text=r["text"], doc_title=r["doc_title"], version=r["version"])
                for r in rows]

    def chunks_revision(self, tenant_id: str) -> int:
        """チャンク集合の版(件数+最大id). 検索インデックスのキャッシュ判定に使う."""
        validate_tenant(tenant_id)
        with self._lock:
            row = self.conn.execute(
                "SELECT COUNT(*) AS n, COALESCE(MAX(id),0) AS mx FROM chunks WHERE tenant_id=?",
                (tenant_id,)).fetchone()
        return int(row["n"]) * 1_000_003 + int(row["mx"])

    def delete_chunks(self, tenant_id: str, doc_id: str = "") -> int:
        validate_tenant(tenant_id)
        with self._lock:
            if doc_id:
                cur = self.conn.execute(
                    "DELETE FROM chunks WHERE tenant_id=? AND doc_id=?", (tenant_id, doc_id))
            else:
                cur = self.conn.execute("DELETE FROM chunks WHERE tenant_id=?", (tenant_id,))
            self.conn.commit()
            return cur.rowcount

    # --- approvals ---
    def save_approval(self, tenant_id: str, req_id: str, requester: str, title: str,
                      detail: str, approver: str, status: str,
                      required_approver: str = "", amount: Optional[int] = None,
                      requires_manual_review: bool = False) -> None:
        validate_tenant(tenant_id)
        with self._lock:
            self.conn.execute(
                "INSERT INTO approvals(tenant_id, req_id, requester, title, detail, approver,"
                " required_approver, amount, requires_manual_review, status) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (tenant_id, req_id, requester, title, detail, approver,
                 required_approver or approver, amount, int(requires_manual_review), status))
            self.conn.commit()

    def update_approval(self, tenant_id: str, req_id: str, status: str,
                        approver: str = "") -> int:
        validate_tenant(tenant_id)
        with self._lock:
            cur = self.conn.execute(
                "UPDATE approvals SET status=?, approver=COALESCE(NULLIF(?,''), approver), "
                "updated_at=datetime('now') WHERE tenant_id=? AND req_id=?",
                (status, approver, tenant_id, req_id))
            self.conn.commit()
            return cur.rowcount

    def get_approval(self, tenant_id: str, req_id: str) -> Optional[dict]:
        validate_tenant(tenant_id)
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM approvals WHERE tenant_id=? AND req_id=?",
                (tenant_id, req_id)).fetchone()
        return dict(row) if row else None

    def list_approvals(self, tenant_id: str, status: str = "", limit: int = 200,
                       offset: int = 0) -> List[dict]:
        validate_tenant(tenant_id)
        limit = max(1, min(int(limit), 1000))
        sql = ("SELECT req_id, requester, title, detail, approver, required_approver, "
               "amount, requires_manual_review, status, created_at, updated_at "
               "FROM approvals WHERE tenant_id=?")
        params: List = [tenant_id]
        if status:
            sql += " AND status=?"
            params.append(status)
        sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
        params += [limit, max(int(offset), 0)]
        with self._lock:
            rows = self.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    # --- audit ---
    def append_audit(self, tenant_id: str, entry: Dict) -> None:
        validate_tenant(tenant_id)
        with self._lock:
            self.conn.execute(
                "INSERT OR IGNORE INTO audit"
                "(tenant_id, seq, ts, actor, action, detail, prev_hash, hash) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (tenant_id, entry["seq"], entry["ts"], entry["actor"], entry["action"],
                 json.dumps(entry.get("detail", {}), ensure_ascii=False),
                 entry.get("prev_hash", ""), entry.get("hash", "")))
            self.conn.commit()

    def list_audit(self, tenant_id: str, limit: int = 200, offset: int = 0) -> List[dict]:
        validate_tenant(tenant_id)
        limit = max(1, min(int(limit), 1000))
        with self._lock:
            rows = self.conn.execute(
                "SELECT seq, ts, actor, action, detail, prev_hash, hash FROM audit "
                "WHERE tenant_id=? ORDER BY seq DESC LIMIT ? OFFSET ?",
                (tenant_id, limit, max(int(offset), 0))).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["detail"] = json.loads(d["detail"])
            except (TypeError, ValueError):
                d["detail"] = {}
            out.append(d)
        return out

    def close(self) -> None:
        with self._lock:
            self.conn.close()
