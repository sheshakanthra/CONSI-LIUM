"""End-to-end ingestion integration test.

Ingests a synthetic sample PDF (prose + a financial table) and the sample
earnings-call audio clip, then asserts the rows actually landed in Postgres
with the right shape:

  filings / filing_chunks / filing_tables      (from the PDF)
  transcripts / transcript_segments            (from the audio)

WHY this is marked ``integration`` and may skip: it needs a live Postgres and,
for the audio half, downloads a tiny Whisper model. If the DB is unreachable the
whole test skips (no false failures in a DB-less environment); if the sample
audio file is absent, only the audio assertions skip. The intended way to run it
is inside the api container where both the DB and /data are available:

    docker compose exec api pytest tests/test_ingestion.py -v
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select, text

from app.config import get_settings
from app.db import SessionLocal, engine
from ingestion import pipeline
from ingestion.generate_samples import generate_samples
from ingestion.models import (
    Filing,
    FilingChunk,
    FilingTable,
    Transcript,
    TranscriptSegment,
)

# loop_scope="session" keeps every test on the same event loop as the
# session-scoped DB fixture, so the shared async engine's pool stays valid.
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
async def _prepared_db():
    """Skip if no DB; otherwise create the schema and start from a clean slate."""
    # Dispose first: a sync test earlier in the session (e.g. the health check's
    # TestClient) may have used the module-level async engine on a now-closed
    # loop, leaving stale pooled connections. Disposing drops them so the pool
    # rebinds to *this* session loop instead of reporting the DB unreachable.
    await engine.dispose()
    if not await _db_reachable():
        pytest.skip("Postgres not reachable (set DATABASE_URL / start docker compose)")

    await pipeline.create_schema()
    # TRUNCATE ... RESTART IDENTITY CASCADE gives every test run a clean,
    # deterministic starting point on the dev database.
    async with engine.begin() as conn:
        await conn.execute(
            text(f"TRUNCATE {', '.join(_TABLES)} RESTART IDENTITY CASCADE")
        )
    yield


async def _count(session, model) -> int:
    return (await session.execute(select(func.count()).select_from(model))).scalar_one()


async def test_pdf_ingestion_lands_rows():
    settings = get_settings()
    # Regenerate the deterministic sample so the test never depends on whatever
    # PDFs happen to be sitting in the filings dir.
    generate_samples(settings.filings_dir)
    pdf_path = Path(settings.filings_dir) / "sample_filing_01.pdf"
    assert pdf_path.is_file(), "sample filing was not generated"

    async with SessionLocal() as session:
        result = await pipeline.ingest_filing(session, pdf_path, settings)

    assert result.is_new is True
    assert result.num_pages >= 1
    assert result.num_chunks > 0
    assert result.num_tables >= 1  # the sample PDF contains a financial table

    async with SessionLocal() as session:
        assert await _count(session, Filing) == 1
        assert await _count(session, FilingChunk) == result.num_chunks
        assert await _count(session, FilingTable) == result.num_tables

        # The table must be stored *structured* (queryable), not flattened.
        tbl = (
            await session.execute(select(FilingTable).limit(1))
        ).scalar_one()
        assert isinstance(tbl.rows, list) and tbl.rows, "table rows not stored as JSONB list"
        assert isinstance(tbl.columns, list) and tbl.columns
        assert tbl.n_cols == len(tbl.columns)
        # A known cell from the generated financial table survived extraction.
        flat = [c for row in ([tbl.columns] + tbl.rows) for c in row if c]
        assert any("Revenue" in c for c in flat), "expected 'Revenue' cell in table"

        # A chunk must carry real text and a source page for later citation.
        chunk = (
            await session.execute(
                select(FilingChunk).order_by(FilingChunk.chunk_index).limit(1)
            )
        ).scalar_one()
        assert chunk.text.strip()
        assert chunk.page_number is not None
        assert chunk.char_count == len(chunk.text)


async def test_pdf_ingestion_is_idempotent():
    settings = get_settings()
    pdf_path = Path(settings.filings_dir) / "sample_filing_01.pdf"

    async with SessionLocal() as session:
        again = await pipeline.ingest_filing(session, pdf_path, settings)

    # Same file, already ingested by the previous test -> no new rows.
    assert again.is_new is False
    async with SessionLocal() as session:
        assert await _count(session, Filing) == 1


async def test_audio_ingestion_lands_timestamped_segments():
    settings = get_settings()
    audio_path = Path(settings.transcripts_dir) / "sample_earnings_call.wav"
    if not audio_path.is_file():
        pytest.skip(
            "sample audio missing; generate it via "
            "apps/api/ingestion/generate_sample_audio.ps1"
        )

    async with SessionLocal() as session:
        result = await pipeline.ingest_audio(session, audio_path, settings)

    assert result.is_new is True
    assert result.num_segments > 0
    assert result.language  # Whisper detected a language

    async with SessionLocal() as session:
        assert await _count(session, Transcript) == 1
        assert await _count(session, TranscriptSegment) == result.num_segments

        seg = (
            await session.execute(
                select(TranscriptSegment).order_by(TranscriptSegment.segment_index).limit(1)
            )
        ).scalar_one()
        # Timestamps must be real and ordered; text must be non-empty.
        assert seg.end_seconds >= seg.start_seconds
        assert seg.text.strip()
