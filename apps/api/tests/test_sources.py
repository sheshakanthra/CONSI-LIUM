"""Citation-resolution tests: GET /sources/{source_type}/{source_id}.

Two layers, deliberately split:

1. **Unit** (no DB) — the endpoint's *contract* for bad input. A malformed
   ``source_type`` must be rejected by FastAPI's enum validation before any
   query runs, so this is assertable without Postgres (sync ``TestClient`` is
   fine here precisely *because* nothing touches the database).

2. **Integration** (needs DB) — the thing that actually matters: a citation
   emitted by the retrieval layer resolves back to the *same* evidence the
   answer was drawn from. That round-trip is the project's traceability claim;
   asserting it here is what stops the dashboard from linking to plausible-
   looking but wrong sources.

WHY the DB-backed tests use httpx's ASGITransport instead of ``TestClient``:
``TestClient`` drives the app from a worker thread on its **own** event loop,
but ``app.db.engine``'s asyncpg pool is bound to the session-scoped loop (see
the note in pytest.ini). Crossing those loops raises "got Future attached to a
different loop" the moment an endpoint opens a session. ``AsyncClient`` +
``ASGITransport`` awaits the app *in the current loop*, so the endpoint's
session and the fixtures' sessions share one loop — the same constraint the rest
of the suite already lives under.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

from app.config import get_settings
from app.db import SessionLocal, engine
from app.main import app
from ingestion import pipeline
from ingestion.generate_samples import generate_samples
from ingestion.models import Filing, FilingChunk, FilingTable
from retrieval.indexer import build_index
from retrieval.schema import ensure_vector_schema
from retrieval.service import QAService

# Sync client for the no-DB tests only. Named distinctly from the async `client`
# fixture below so it's obvious at each call site which one is in play.
sync_client = TestClient(app)


# --------------------------------------------------------------------------- #
# Unit: input validation (no DB required)                                      #
# --------------------------------------------------------------------------- #
def test_unknown_source_type_is_rejected() -> None:
    """A source_type outside the SourceKind enum is a 422, not a DB miss.

    WHY assert this: it pins the enum-in-the-path design. If someone later
    widens the param to a bare ``str``, this fails — and the endpoint would
    otherwise silently turn a typo into a 404, which reads like "no such
    evidence" rather than "you asked for a kind that doesn't exist".
    """
    resp = sync_client.get("/sources/transcript/1")
    assert resp.status_code == 422


def test_non_positive_source_id_is_rejected() -> None:
    """ids are 1-based serials; 0 / negatives can't exist, so reject early."""
    assert sync_client.get("/sources/chunk/0").status_code == 422


# --------------------------------------------------------------------------- #
# Integration: the citation round-trip                                         #
# --------------------------------------------------------------------------- #
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


@pytest.fixture(scope="session")
async def indexed_db():
    """Ingest + embed the sample filing on a clean DB; skip if no Postgres.

    Mirrors ``test_retrieval.py``'s fixture (same ordering constraints: vector
    extension -> tables -> ALTER). Not shared via conftest because the two
    suites are independently runnable and neither should imply the other's
    setup cost.
    """
    await engine.dispose()  # rebind pool to this (session) loop; see phase-1 note
    if not await _db_reachable():
        pytest.skip("Postgres not reachable (start docker compose)")

    settings = get_settings()
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


@pytest.fixture
async def client():
    """In-loop ASGI client (see the module docstring for why not TestClient)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_chunk_citation_resolves_to_its_text(indexed_db, client) -> None:
    """The text a chunk citation points at is the text stored for that chunk."""
    async with SessionLocal() as session:
        chunk = (
            await session.execute(select(FilingChunk).order_by(FilingChunk.id).limit(1))
        ).scalar_one()
        filing = (
            await session.execute(select(Filing).where(Filing.id == chunk.filing_id))
        ).scalar_one()
        expected_text, expected_index = chunk.text, chunk.chunk_index
        expected_file, expected_page = filing.file_name, chunk.page_number

    resp = await client.get(f"/sources/chunk/{chunk.id}")
    assert resp.status_code == 200
    body = resp.json()

    assert body["source_type"] == "chunk"
    assert body["source_id"] == chunk.id
    assert body["chunk"]["text"] == expected_text
    assert body["chunk"]["chunk_index"] == expected_index
    # Provenance must come through — a citation without it isn't checkable.
    assert body["file_name"] == expected_file
    assert body["page_number"] == expected_page
    assert body["table"] is None


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_table_citation_resolves_with_structure_intact(indexed_db, client) -> None:
    """A table citation returns header + rows as a grid, never flattened prose."""
    async with SessionLocal() as session:
        table = (
            await session.execute(select(FilingTable).order_by(FilingTable.id).limit(1))
        ).scalar_one()
        expected_cols, expected_rows = table.columns, table.rows

    resp = await client.get(f"/sources/table/{table.id}")
    assert resp.status_code == 200
    body = resp.json()

    assert body["source_type"] == "table"
    assert body["table"]["columns"] == expected_cols
    assert body["table"]["rows"] == expected_rows
    assert body["chunk"] is None


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_missing_source_is_404(indexed_db, client) -> None:
    """An id past the end of the table is a reported 404, not an empty body."""
    async with SessionLocal() as session:
        max_id = (
            await session.execute(select(FilingChunk.id).order_by(FilingChunk.id.desc()).limit(1))
        ).scalar_one()

    resp = await client.get(f"/sources/chunk/{max_id + 10_000}")
    assert resp.status_code == 404
    assert "no chunk source" in resp.json()["detail"]


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_answer_citations_all_resolve(indexed_db, client) -> None:
    """Every citation the QA layer emits must dereference — no dangling pointers.

    This is the load-bearing assertion of the whole phase: the dashboard renders
    citations as clickable evidence, so a citation that can't be resolved is a
    broken promise, not a cosmetic bug.
    """
    async with SessionLocal() as session:
        filing = (
            await session.execute(
                select(Filing).where(Filing.file_name == "sample_filing_01.pdf")
            )
        ).scalar_one()
        answer = await QAService().answer_question(
            session, "What was revenue in Q1 FY27?", filing.ticker
        )

    assert answer.citations, "expected a grounded answer with at least one citation"
    for citation in answer.citations:
        resp = await client.get(f"/sources/{citation.source_type}/{citation.source_id}")
        assert resp.status_code == 200, (
            f"citation {citation.source_type}:{citation.source_id} did not resolve"
        )
