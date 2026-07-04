"""Vector-schema management for retrieval.

WHY raw ALTERs instead of ``create_all``: the ingestion tables already exist
(Phase 1), and ``Base.metadata.create_all`` only *creates missing tables* — it
won't add the new ``embedding`` / ``ticker`` columns to tables that are already
there. Until Alembic is introduced, this idempotent DDL brings an existing
database up to the Phase 2 schema. On a brand-new database ``create_all`` (via
the ORM models) already includes these columns and these ALTERs are no-ops.

An ANN index (ivfflat/hnsw) is deliberately NOT created: at portfolio corpus
size exact search is fast and avoids the recall tuning an approximate index
needs. See docs/phase2-rag.md.
"""

from __future__ import annotations

from sqlalchemy import text

from app.config import get_settings
from app.db import engine


async def ensure_vector_schema() -> None:
    """Ensure the pgvector extension and the Phase 2 columns exist."""
    dim = get_settings().embedding_dim
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.execute(
            text("ALTER TABLE filings ADD COLUMN IF NOT EXISTS ticker VARCHAR(16)")
        )
        await conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_filings_ticker ON filings (ticker)")
        )
        # Column dim is interpolated (not a bind param) because it's part of the
        # type, not a value; it comes from our own settings, not user input.
        await conn.execute(
            text(
                f"ALTER TABLE filing_chunks "
                f"ADD COLUMN IF NOT EXISTS embedding vector({dim})"
            )
        )
        await conn.execute(
            text(
                f"ALTER TABLE transcript_segments "
                f"ADD COLUMN IF NOT EXISTS embedding vector({dim})"
            )
        )
