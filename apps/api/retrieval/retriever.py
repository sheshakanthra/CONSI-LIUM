"""Hybrid, per-ticker chunk retriever.

Combines two signals over ``filing_chunks``, always scoped to one ticker:

1. **Vector similarity** — cosine distance between the query embedding and each
   chunk embedding (pgvector ``<=>``). Great for paraphrase/semantic matches.
2. **Keyword** — Postgres full-text ``to_tsvector @@ plainto_tsquery`` ranked by
   ``ts_rank``. A robust fallback when the question shares exact terms with the
   text (numbers, proper nouns) and a safety net if embeddings are missing.

WHY fuse with Reciprocal Rank Fusion (RRF): the two scores live on different,
non-comparable scales (cosine similarity vs ts_rank). RRF combines by *rank*,
not raw score, so we don't have to calibrate one against the other — each result
contributes ``1/(rrf_k + rank)`` from each list. Simple, order-robust, and the
standard cheap hybrid-search recipe.

Vector similarity (0..1) is still carried through on each result so the answerer
can band confidence and trip the "insufficient evidence" path.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import bindparam, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from ingestion.models import Filing, FilingChunk
from retrieval.embeddings import Embedder


@dataclass
class RetrievedChunk:
    chunk_id: int
    filing_id: int
    page_number: int | None
    text: str
    # Cosine similarity in [0, 1] (1 = identical). None if the chunk only
    # surfaced via keyword search and had no embedding.
    similarity: float | None
    # Fused RRF score used for ordering (higher = better).
    score: float


class Retriever:
    def __init__(self, embedder: Embedder | None = None, settings: Settings | None = None):
        self._settings = settings or get_settings()
        self._embedder = embedder or Embedder()

    async def _vector_hits(
        self, session: AsyncSession, ticker: str, query: str, k: int
    ) -> list[tuple[int, float]]:
        """Return [(chunk_id, similarity)] by cosine distance, best first."""
        qvec = self._embedder.embed_query(query)
        # cosine_distance is in [0, 2]; similarity = 1 - distance for normalized
        # embeddings (bge outputs are normalized), giving [0, 1] in practice.
        distance = FilingChunk.embedding.cosine_distance(qvec).label("distance")
        stmt = (
            select(FilingChunk.id, distance)
            .join(Filing, Filing.id == FilingChunk.filing_id)
            .where(Filing.ticker == ticker)
            .where(FilingChunk.embedding.is_not(None))
            .order_by(distance)
            .limit(k)
        )
        rows = (await session.execute(stmt)).all()
        return [(cid, 1.0 - float(dist)) for cid, dist in rows]

    async def _keyword_hits(
        self, session: AsyncSession, ticker: str, query: str, k: int
    ) -> list[int]:
        """Return chunk_ids ranked by full-text relevance, best first."""
        stmt = (
            text(
                """
                SELECT fc.id
                FROM filing_chunks fc
                JOIN filings f ON f.id = fc.filing_id
                WHERE f.ticker = :ticker
                  AND to_tsvector('english', fc.text)
                      @@ plainto_tsquery('english', :query)
                ORDER BY ts_rank(
                    to_tsvector('english', fc.text),
                    plainto_tsquery('english', :query)
                ) DESC
                LIMIT :k
                """
            )
            .bindparams(
                bindparam("ticker", ticker),
                bindparam("query", query),
                bindparam("k", k),
            )
        )
        return [row[0] for row in (await session.execute(stmt)).all()]

    async def retrieve(
        self, session: AsyncSession, ticker: str, query: str, k: int | None = None
    ) -> list[RetrievedChunk]:
        """Hybrid retrieve top-``k`` chunks for ``ticker``."""
        k = k or self._settings.retrieval_top_k
        rrf_k = self._settings.rrf_k

        # Pull a wider candidate pool from each signal, then fuse and cut to k.
        pool = max(k * 4, 20)
        vector_hits = await self._vector_hits(session, ticker, query, pool)
        keyword_ids = await self._keyword_hits(session, ticker, query, pool)

        similarity_by_id = {cid: sim for cid, sim in vector_hits}
        fused: dict[int, float] = {}
        for rank, (cid, _sim) in enumerate(vector_hits):
            fused[cid] = fused.get(cid, 0.0) + 1.0 / (rrf_k + rank)
        for rank, cid in enumerate(keyword_ids):
            fused[cid] = fused.get(cid, 0.0) + 1.0 / (rrf_k + rank)

        if not fused:
            return []

        top_ids = sorted(fused, key=lambda c: fused[c], reverse=True)[:k]

        # Fetch chunk bodies for the winners in one query.
        chunks = {
            c.id: c
            for c in (
                await session.execute(
                    select(FilingChunk).where(FilingChunk.id.in_(top_ids))
                )
            ).scalars()
        }
        results: list[RetrievedChunk] = []
        for cid in top_ids:
            c = chunks.get(cid)
            if c is None:
                continue
            results.append(
                RetrievedChunk(
                    chunk_id=c.id,
                    filing_id=c.filing_id,
                    page_number=c.page_number,
                    text=c.text,
                    similarity=similarity_by_id.get(cid),
                    score=fused[cid],
                )
            )
        return results
