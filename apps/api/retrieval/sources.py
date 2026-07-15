"""Citation -> source resolution.

WHY this module exists: a ``Citation`` is deliberately a *pointer* — a
``source_type`` + ``source_id`` and nothing more (see ``retrieval/types.py``).
That keeps the agent graph's payloads small and stops evidence text from being
copied, and possibly mutated, as it flows between nodes. The cost is that a
citation alone can't be shown to a human: "chunk 412" proves nothing.

This module closes that loop. It resolves a pointer back to the exact evidence
it names — chunk text, or a table's header + cells — together with the parent
filing's provenance (company, file name, page). That is what makes the project's
central claim ("every claim traces to a source page/cell") *checkable by the
reader* rather than merely asserted by the pipeline.

Design notes:
- Resolution is **read-only and by-id**. There is no search here; retrieval
  already decided what the evidence is. This module only dereferences.
- Tables keep their structure (``columns``/``rows``), never flattened to prose —
  same rule as ingestion. The UI renders a real table so a reader can find the
  cited cell.
- A missing id is a first-class ``None`` return, not an exception. The endpoint
  layer decides that means 404; the service stays HTTP-agnostic (same split as
  ``QAService``).
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ingestion.models import Filing, FilingChunk, FilingTable


class SourceKind(str, Enum):
    """The citable source kinds.

    Mirrors the values ``Citation.source_type`` can hold. Declared as an enum so
    the endpoint's path param is validated by FastAPI *before* a DB round-trip —
    a bad kind is a 422, not a query that finds nothing.
    """

    CHUNK = "chunk"
    TABLE = "table"


class ChunkSource(BaseModel):
    """The text-window payload of a resolved ``chunk`` citation."""

    text: str
    chunk_index: int


class TableSource(BaseModel):
    """The structured payload of a resolved ``table`` citation.

    ``columns``/``rows`` come straight from JSONB as ingestion stored them, so
    what the reader sees is what Table QA queried — no re-parse, no drift.
    """

    columns: list
    rows: list
    table_index: int


class SourceDocument(BaseModel):
    """A citation dereferenced to its evidence + provenance.

    Exactly one of ``chunk``/``table`` is populated, matching ``source_type``.
    WHY not one polymorphic ``content`` field: the two payloads are genuinely
    different shapes (prose vs. a grid), and a discriminated pair keeps both the
    Pydantic model and its Zod mirror honest instead of degrading to ``Any``.
    """

    source_type: SourceKind
    source_id: int
    filing_id: int
    company: str | None = None
    ticker: str | None = None
    file_name: str
    page_number: int | None = None
    chunk: ChunkSource | None = None
    table: TableSource | None = None


async def _resolve_chunk(session: AsyncSession, source_id: int) -> SourceDocument | None:
    """Load a filing chunk + its parent filing in one join.

    WHY a single joined select rather than lazy-loading ``chunk.filing``: this
    session is async, and touching a lazy relationship attribute outside an
    awaited load raises. Being explicit about the join is also the CLAUDE.md
    house rule — no ORM magic that hides the SQL.
    """
    stmt = (
        select(FilingChunk, Filing)
        .join(Filing, Filing.id == FilingChunk.filing_id)
        .where(FilingChunk.id == source_id)
    )
    row = (await session.execute(stmt)).first()
    if row is None:
        return None
    chunk, filing = row
    return SourceDocument(
        source_type=SourceKind.CHUNK,
        source_id=chunk.id,
        filing_id=filing.id,
        company=filing.company,
        ticker=filing.ticker,
        file_name=filing.file_name,
        page_number=chunk.page_number,
        chunk=ChunkSource(text=chunk.text, chunk_index=chunk.chunk_index),
    )


async def _resolve_table(session: AsyncSession, source_id: int) -> SourceDocument | None:
    """Load a filing table + its parent filing in one join (see ``_resolve_chunk``)."""
    stmt = (
        select(FilingTable, Filing)
        .join(Filing, Filing.id == FilingTable.filing_id)
        .where(FilingTable.id == source_id)
    )
    row = (await session.execute(stmt)).first()
    if row is None:
        return None
    table, filing = row
    return SourceDocument(
        source_type=SourceKind.TABLE,
        source_id=table.id,
        filing_id=filing.id,
        company=filing.company,
        ticker=filing.ticker,
        file_name=filing.file_name,
        page_number=table.page_number,
        table=TableSource(
            columns=table.columns, rows=table.rows, table_index=table.table_index
        ),
    )


async def resolve_source(
    session: AsyncSession, kind: SourceKind, source_id: int
) -> SourceDocument | None:
    """Dereference one citation. Returns ``None`` if the id doesn't exist.

    Kept as a thin dispatch so each kind's query stays readable on its own; the
    two shapes share no SQL worth factoring together.
    """
    if kind is SourceKind.CHUNK:
        return await _resolve_chunk(session, source_id)
    return await _resolve_table(session, source_id)
