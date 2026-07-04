"""Retrieval / QA integration test: 5 Q&A pairs against the sample filing.

Asserts the whole path — router -> retrieve/table -> extractive answer — and,
crucially, that every grounded answer carries a **correct** citation (a real
chunk/table id on the right filing and page), and that an unanswerable question
yields "insufficient evidence" with no citations.

Marked ``integration``: needs Postgres and downloads the embedding model. Skips
cleanly if the DB is unreachable.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select, text

from app.config import get_settings
from app.db import SessionLocal, engine
from ingestion import pipeline
from ingestion.generate_samples import generate_samples
from ingestion.models import Filing, FilingChunk, FilingTable
from retrieval.indexer import build_index
from retrieval.schema import ensure_vector_schema
from retrieval.service import QAService
from retrieval.types import QAPath

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]

_TABLES = [
    "transcript_segments",
    "transcripts",
    "filing_chunks",
    "filing_tables",
    "filings",
]


async def _db_reachable() -> bool:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@pytest.fixture(scope="session", autouse=True)
async def _indexed_db():
    """Ingest + embed the sample filing on a clean DB; skip if no Postgres."""
    await engine.dispose()  # rebind pool to this (session) loop; see phase-1 note
    if not await _db_reachable():
        pytest.skip("Postgres not reachable (start docker compose)")

    settings = get_settings()
    # Extension must exist before create_all builds the Vector columns; tables
    # must exist before ensure_vector_schema ALTERs them. Hence this order.
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    await pipeline.create_schema()
    await ensure_vector_schema()
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {', '.join(_TABLES)} RESTART IDENTITY CASCADE"))

    generate_samples(settings.filings_dir)
    async with SessionLocal() as session:
        await pipeline.ingest_filing(
            session, Path(settings.filings_dir) / "sample_filing_01.pdf", settings
        )
    async with SessionLocal() as session:
        await build_index(session)
    yield


@pytest.fixture(scope="session")
async def ticker() -> str:
    async with SessionLocal() as session:
        filing = (
            await session.execute(
                select(Filing).where(Filing.file_name == "sample_filing_01.pdf")
            )
        ).scalar_one()
    assert filing.ticker, "indexer did not assign a ticker"
    return filing.ticker


async def _valid_chunk_ids(ticker: str) -> set[int]:
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(FilingChunk.id)
                .join(Filing, Filing.id == FilingChunk.filing_id)
                .where(Filing.ticker == ticker)
            )
        ).scalars().all()
    return set(rows)


async def _valid_table_ids(ticker: str) -> set[int]:
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(FilingTable.id)
                .join(Filing, Filing.id == FilingTable.filing_id)
                .where(Filing.ticker == ticker)
            )
        ).scalars().all()
    return set(rows)


# (question, expected_path, substring the answer must contain)
_TABLE_CASES = [
    ("What was revenue in Q1 FY27?", "1,245"),
    ("What was net profit?", "188"),
    ("What was EPS?", "9.40"),
]


@pytest.mark.parametrize("question,expected_value", _TABLE_CASES)
async def test_table_qa_answers_with_table_citation(ticker, question, expected_value):
    service = QAService()
    async with SessionLocal() as session:
        ans = await service.answer_question(session, question, ticker)

    assert ans.path is QAPath.TABLE, f"expected table path for {question!r}"
    assert ans.sufficient is True
    assert expected_value in ans.answer
    assert ans.confidence.value == "high"

    # Citation present and correct: a real table id on this ticker, page 1.
    assert len(ans.citations) == 1
    cite = ans.citations[0]
    assert cite.source_type == "table"
    assert cite.source_id in await _valid_table_ids(ticker)
    assert cite.page_number == 1


async def test_document_qa_answers_with_chunk_citation(ticker):
    service = QAService()
    async with SessionLocal() as session:
        ans = await service.answer_question(
            session, "What did the board recommend?", ticker
        )

    assert ans.path is QAPath.DOCUMENT
    assert ans.sufficient is True
    assert "dividend" in ans.answer.lower()

    assert len(ans.citations) == 1
    cite = ans.citations[0]
    assert cite.source_type == "chunk"
    assert cite.source_id in await _valid_chunk_ids(ticker)
    assert cite.page_number == 1


async def test_insufficient_evidence_has_no_citation(ticker):
    service = QAService()
    async with SessionLocal() as session:
        ans = await service.answer_question(
            session, "What is the CEO's favorite color?", ticker
        )

    assert ans.sufficient is False
    assert ans.confidence.value == "none"
    assert ans.citations == []
    assert "insufficient evidence" in ans.answer.lower()
