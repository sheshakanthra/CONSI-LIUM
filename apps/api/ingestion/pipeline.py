"""Ingestion orchestration: parse -> structure -> persist.

This module is the only place that writes ingestion rows. It ties together the
parsers (PDF, chunking, ASR) and the ORM models, and enforces idempotency via
the ``content_hash`` unique keys so re-running is safe.

WHY return a small result object instead of the ORM instance: callers (CLI,
tests) mostly want counts and "was it new or a duplicate?", and returning a
detached ORM object across session boundaries invites lazy-load surprises.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db import Base, engine
from ingestion import asr, chunking
from ingestion.hashing import sha256_file
from ingestion.models import (
    Filing,
    FilingChunk,
    FilingTable,
    Transcript,
    TranscriptSegment,
)
from ingestion.pdf_parser import parse_pdf


@dataclass
class FilingResult:
    filing_id: int
    file_name: str
    is_new: bool
    num_pages: int
    num_chunks: int
    num_tables: int


@dataclass
class TranscriptResult:
    transcript_id: int
    file_name: str
    is_new: bool
    language: str | None
    duration_seconds: float | None
    num_segments: int


async def create_schema() -> None:
    """Create all ingestion tables if they don't exist.

    WHY create_all (not Alembic) for now: the schema is greenfield and moving;
    a migration tool is warranted once it stabilises. Importing ``models`` here
    guarantees every table is registered on ``Base.metadata`` before create.
    """
    from ingestion import models  # noqa: F401 — ensure tables are registered.

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def ingest_filing(
    session: AsyncSession, path: str | Path, settings: Settings
) -> FilingResult:
    """Parse one PDF and persist its filing, chunks, and tables.

    Idempotent: if a filing with the same content hash already exists, returns
    that filing's counts with ``is_new=False`` and writes nothing.
    """
    pdf_path = Path(path)
    content_hash = sha256_file(pdf_path)

    existing = (
        await session.execute(
            select(Filing).where(Filing.content_hash == content_hash)
        )
    ).scalar_one_or_none()
    if existing is not None:
        n_chunks = len(
            (
                await session.execute(
                    select(FilingChunk.id).where(FilingChunk.filing_id == existing.id)
                )
            ).all()
        )
        n_tables = len(
            (
                await session.execute(
                    select(FilingTable.id).where(FilingTable.filing_id == existing.id)
                )
            ).all()
        )
        return FilingResult(
            filing_id=existing.id,
            file_name=existing.file_name,
            is_new=False,
            num_pages=existing.num_pages,
            num_chunks=n_chunks,
            num_tables=n_tables,
        )

    parsed = parse_pdf(pdf_path)
    chunks = chunking.chunk_pages(
        parsed.pages,
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
    )

    filing = Filing(
        source="local_sample",
        title=pdf_path.stem,
        file_name=pdf_path.name,
        file_path=str(pdf_path),
        content_hash=content_hash,
        num_pages=parsed.num_pages,
    )
    filing.chunks = [
        FilingChunk(
            chunk_index=c.chunk_index,
            page_number=c.page_number,
            text=c.text,
            char_count=c.char_count,
        )
        for c in chunks
    ]
    filing.tables = [
        FilingTable(
            page_number=t.page_number,
            table_index=t.table_index,
            n_rows=t.n_rows,
            n_cols=t.n_cols,
            columns=t.columns,
            rows=t.rows,
        )
        for t in parsed.tables
    ]

    session.add(filing)
    await session.flush()  # assign filing.id before we return it
    result = FilingResult(
        filing_id=filing.id,
        file_name=filing.file_name,
        is_new=True,
        num_pages=filing.num_pages,
        num_chunks=len(filing.chunks),
        num_tables=len(filing.tables),
    )
    await session.commit()
    return result


async def ingest_audio(
    session: AsyncSession, path: str | Path, settings: Settings
) -> TranscriptResult:
    """Transcribe one audio file and persist its transcript + segments.

    Idempotent on the audio file's content hash.
    """
    audio_path = Path(path)
    content_hash = sha256_file(audio_path)

    existing = (
        await session.execute(
            select(Transcript).where(Transcript.content_hash == content_hash)
        )
    ).scalar_one_or_none()
    if existing is not None:
        n_segments = len(
            (
                await session.execute(
                    select(TranscriptSegment.id).where(
                        TranscriptSegment.transcript_id == existing.id
                    )
                )
            ).all()
        )
        return TranscriptResult(
            transcript_id=existing.id,
            file_name=existing.audio_file_name,
            is_new=False,
            language=existing.language,
            duration_seconds=existing.duration_seconds,
            num_segments=n_segments,
        )

    data = asr.transcribe(audio_path, settings)

    transcript = Transcript(
        source="local_sample",
        audio_file_name=audio_path.name,
        audio_file_path=str(audio_path),
        content_hash=content_hash,
        language=data.language,
        duration_seconds=data.duration,
        model_name=data.model_name,
    )
    transcript.segments = [
        TranscriptSegment(
            segment_index=s.index,
            start_seconds=s.start,
            end_seconds=s.end,
            text=s.text,
        )
        for s in data.segments
    ]

    session.add(transcript)
    await session.flush()
    result = TranscriptResult(
        transcript_id=transcript.id,
        file_name=transcript.audio_file_name,
        is_new=True,
        language=transcript.language,
        duration_seconds=transcript.duration_seconds,
        num_segments=len(transcript.segments),
    )
    await session.commit()
    return result
