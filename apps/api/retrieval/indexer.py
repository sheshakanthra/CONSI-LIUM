"""Backfill company/ticker metadata and vector embeddings.

Runs after ingestion. Idempotent: only fills rows that are missing data, so it's
safe to re-run (e.g., after ingesting more filings).

WHY derive ticker here rather than in ingestion: ticker isn't reliably present
in the raw PDF text, and Phase 1 deliberately stayed a dumb parse->persist
pipeline. Retrieval is the layer that *needs* a per-ticker scope, so it owns the
(best-effort) derivation: company = the document's first text line; ticker = a
slug of the company's first word. A real system would map to an official symbol.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ingestion.models import Filing, FilingChunk, TranscriptSegment
from retrieval.embeddings import Embedder


@dataclass
class IndexStats:
    filings_updated: int
    chunks_embedded: int
    segments_embedded: int


def _derive_ticker(company: str) -> str:
    """Slug a company name into a stubby ticker (e.g. 'Acme Industries' -> 'ACME')."""
    first = re.sub(r"[^A-Za-z0-9]", "", company.split()[0]) if company.split() else ""
    return first[:6].upper() or "UNKNOWN"


async def backfill_metadata(session: AsyncSession) -> int:
    """Fill ``company``/``ticker`` for filings that lack them.

    company is taken from the first line of the filing's first chunk; ticker is
    derived from company.
    """
    filings = (
        await session.execute(
            select(Filing).where((Filing.ticker.is_(None)) | (Filing.company.is_(None)))
        )
    ).scalars().all()

    updated = 0
    for filing in filings:
        first_chunk = (
            await session.execute(
                select(FilingChunk)
                .where(FilingChunk.filing_id == filing.id)
                .order_by(FilingChunk.chunk_index)
                .limit(1)
            )
        ).scalar_one_or_none()
        if first_chunk is None:
            continue
        first_line = next(
            (ln.strip() for ln in first_chunk.text.splitlines() if ln.strip()), ""
        )
        if filing.company is None and first_line:
            filing.company = first_line[:256]
        if filing.ticker is None and filing.company:
            filing.ticker = _derive_ticker(filing.company)
        updated += 1

    await session.commit()
    return updated


async def _backfill_embeddings_for(
    session: AsyncSession, model, embedder: Embedder, id_attr: str = "id"
) -> int:
    """Embed all rows of ``model`` whose ``embedding`` is NULL."""
    rows = (
        await session.execute(select(model).where(model.embedding.is_(None)))
    ).scalars().all()
    if not rows:
        return 0

    vectors = embedder.embed_documents([r.text for r in rows])
    for row, vec in zip(rows, vectors, strict=True):
        row.embedding = vec
    await session.commit()
    return len(rows)


async def backfill_embeddings(session: AsyncSession, embedder: Embedder) -> tuple[int, int]:
    """Embed filing chunks and transcript segments that don't have vectors yet."""
    n_chunks = await _backfill_embeddings_for(session, FilingChunk, embedder)
    n_segments = await _backfill_embeddings_for(session, TranscriptSegment, embedder)
    return n_chunks, n_segments


async def build_index(session: AsyncSession, embedder: Embedder | None = None) -> IndexStats:
    """Run the full backfill: metadata first, then embeddings."""
    embedder = embedder or Embedder()
    filings_updated = await backfill_metadata(session)
    n_chunks, n_segments = await backfill_embeddings(session, embedder)
    return IndexStats(
        filings_updated=filings_updated,
        chunks_embedded=n_chunks,
        segments_embedded=n_segments,
    )
