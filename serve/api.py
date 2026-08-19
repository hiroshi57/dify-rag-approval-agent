"""[非推奨] 旧エントリポイント. 実体は service.api に統合済み.

旧 `serve/api.py` と `service/api.py` は QA・承認・監査のロジックを二重に持ち、
片方だけ修正されて挙動が食い違う状態だった(DRY 違反)。
現在は service.api を唯一の実装とし、本モジュールは

  - docs/ のサンプル規程をデモ用テナントへ自動投入する
  - 後方互換のため `app` を公開する

だけの薄いシムである。新規利用は `uvicorn service.api:app` を使うこと。
"""
from __future__ import annotations

import logging
import os
import warnings

from rag_agent import ingest_dir
from service.api import AppContext, create_app as _create_service_app

logger = logging.getLogger(__name__)

DOCS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs")
DEMO_TENANT = os.getenv("RAG_DEMO_TENANT", "demo")


def create_app(context: AppContext | None = None):
    warnings.warn(
        "serve.api は非推奨です。service.api:app を使用してください。",
        DeprecationWarning, stacklevel=2)
    ctx = context or AppContext()
    chunks = ingest_dir(DOCS)
    ctx.db.add_chunks(DEMO_TENANT, chunks)
    logger.info("デモ用テナント %s に %d チャンクを投入しました", DEMO_TENANT, len(chunks))
    return _create_service_app(ctx)


def _build_default_app():
    try:
        import fastapi  # noqa: F401
    except ImportError:
        logger.warning("FastAPI 未インストールのため serve.api:app は生成されません")
        return None
    return create_app()


app = _build_default_app()
