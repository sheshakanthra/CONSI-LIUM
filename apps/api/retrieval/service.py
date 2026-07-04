"""QA service: orchestrates routing, retrieval, and answering.

Flow for ``answer_question(question, ticker)``:
  1. Router picks TABLE or DOCUMENT.
  2. TABLE -> structured lookup. If it can't find the figure, we *fall back* to
     the document path (a mis-route shouldn't strand a valid narrative answer)
     and record that in ``router_reason``.
  3. DOCUMENT -> hybrid retrieve -> extractive answer -> confidence banding.
  4. If nothing grounds an answer, return the canonical "insufficient evidence".

Confidence banding (document path) is derived from the chosen chunk's cosine
similarity, floored so a grounded-but-weak match still reads as LOW rather than
overclaiming.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from retrieval import router as query_router
from retrieval import table_qa
from retrieval.answerer import ExtractiveAnswerer
from retrieval.embeddings import Embedder
from retrieval.retriever import Retriever
from retrieval.types import Answer, Citation, Confidence, QAPath


class QAService:
    def __init__(
        self,
        embedder: Embedder | None = None,
        retriever: Retriever | None = None,
        answerer: ExtractiveAnswerer | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._embedder = embedder or Embedder()
        self._retriever = retriever or Retriever(self._embedder, self._settings)
        self._answerer = answerer or ExtractiveAnswerer()

    def _band(self, similarity: float | None) -> Confidence:
        """Map a cosine similarity to a coarse confidence band."""
        if similarity is None:
            return Confidence.LOW  # grounded via keyword only, no vector score
        if similarity >= 0.6:
            return Confidence.HIGH
        if similarity >= 0.45:
            return Confidence.MEDIUM
        return Confidence.LOW

    async def _answer_document(
        self, session: AsyncSession, question: str, ticker: str, reason: str
    ) -> Answer:
        retrieved = await self._retriever.retrieve(session, ticker, question)
        doc = self._answerer.answer(question, retrieved)

        if not doc.sufficient or doc.chunk is None:
            return Answer.insufficient(question, ticker, QAPath.DOCUMENT, reason)

        chunk = doc.chunk
        return Answer(
            question=question,
            ticker=ticker,
            path=QAPath.DOCUMENT,
            answer=doc.text,
            sufficient=True,
            confidence=self._band(chunk.similarity),
            citations=[
                Citation(
                    source_type="chunk",
                    source_id=chunk.chunk_id,
                    filing_id=chunk.filing_id,
                    page_number=chunk.page_number,
                    similarity=chunk.similarity,
                )
            ],
            router_reason=reason,
        )

    async def answer_question(
        self, session: AsyncSession, question: str, ticker: str
    ) -> Answer:
        path, reason = query_router.route(question)

        if path is QAPath.TABLE:
            table_answer = await table_qa.answer_from_tables(
                session, ticker, question, router_reason=reason
            )
            if table_answer.sufficient:
                return table_answer
            # Mis-route or figure not in a table -> try the narrative path.
            fallback_reason = f"{reason}; table lookup empty, fell back to document"
            return await self._answer_document(session, question, ticker, fallback_reason)

        return await self._answer_document(session, question, ticker, reason)
