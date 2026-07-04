"""CLI to build the retrieval index over already-ingested data.

    python -m retrieval.index

Ensures the vector schema exists, backfills company/ticker, and embeds any
chunks/segments that don't yet have vectors. Idempotent — safe to re-run after
ingesting more filings.
"""

from __future__ import annotations

import asyncio

from app.db import SessionLocal
from retrieval.indexer import build_index
from retrieval.schema import ensure_vector_schema


async def _main() -> int:
    await ensure_vector_schema()
    async with SessionLocal() as session:
        stats = await build_index(session)
    print(
        f"[index] filings metadata updated: {stats.filings_updated}, "
        f"chunks embedded: {stats.chunks_embedded}, "
        f"segments embedded: {stats.segments_embedded}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
