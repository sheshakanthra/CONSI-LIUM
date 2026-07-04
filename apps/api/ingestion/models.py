"""SQLAlchemy 2.0 ORM schema for the ingestion layer.

WHY these tables (and why they're shaped this way):

- ``filings`` is the parent document. Every filing carries a ``content_hash``
  (sha256 of the file bytes) with a UNIQUE constraint so re-running ingestion
  on the same file is idempotent — we detect and skip duplicates instead of
  piling up rows.
- ``filing_chunks`` holds overlapping *text* windows for later embedding /
  retrieval. It intentionally does NOT hold tables.
- ``filing_tables`` keeps tables **structured** (header + rows as JSONB) rather
  than flattened into prose, because Table QA later needs to query cells, not
  grep sentences. This separation is the core design choice of this phase.
- ``transcripts`` / ``transcript_segments`` mirror the same parent/child shape
  for ASR output, with per-segment start/end timestamps preserved.

Per CLAUDE.md we use explicit column types, explicit FKs, and explicit UNIQUE
constraints — no implicit/magic mappings. Cascades are declared on both the ORM
relationship (``cascade="all, delete-orphan"``) and the DB FK
(``ondelete="CASCADE"``) so deleting a parent cleans up children whether the
delete goes through the ORM or raw SQL.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config import get_settings
from app.db import Base

# Embedding dimensionality is pinned by the chosen model (bge-small-en-v1.5 =>
# 384). Read from settings so the column and the embedder can't drift apart.
_EMBEDDING_DIM = get_settings().embedding_dim


class Filing(Base):
    """A single source document (e.g., a PDF filing)."""

    __tablename__ = "filings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Provenance of the document. "local_sample" for this phase; a real fetcher
    # would set e.g. "nse" plus a source URL.
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="local_sample")
    company: Mapped[str | None] = mapped_column(String(256))
    # Ticker symbol used to scope retrieval per-company. Populated by ingestion
    # (derived from the document) / backfilled by the retrieval indexer.
    ticker: Mapped[str | None] = mapped_column(String(16), index=True)
    title: Mapped[str | None] = mapped_column(Text)
    file_name: Mapped[str] = mapped_column(String(512), nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    # sha256 of the raw file bytes — the idempotency key for ingestion.
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    num_pages: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    chunks: Mapped[list[FilingChunk]] = relationship(
        back_populates="filing", cascade="all, delete-orphan"
    )
    tables: Mapped[list[FilingTable]] = relationship(
        back_populates="filing", cascade="all, delete-orphan"
    )


class FilingChunk(Base):
    """An overlapping window of extracted filing *text* (for retrieval).

    The vector embedding column is intentionally deferred to the retrieval
    phase — its dimensionality depends on the embedding model we pick, and we
    don't want to lock that in prematurely. pgvector is already enabled on the
    database for when it lands.
    """

    __tablename__ = "filing_chunks"
    __table_args__ = (
        UniqueConstraint("filing_id", "chunk_index", name="uq_filing_chunk_index"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filing_id: Mapped[int] = mapped_column(
        ForeignKey("filings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # 0-based ordinal of the chunk within the whole document.
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    # 1-based page the chunk was drawn from (nullable: some text may be
    # page-less depending on the extractor).
    page_number: Mapped[int | None] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False)
    # Nullable: populated by the retrieval indexer after ingestion, not at
    # write time. Dim pinned to the embedding model (see _EMBEDDING_DIM).
    embedding: Mapped[list[float] | None] = mapped_column(Vector(_EMBEDDING_DIM))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    filing: Mapped[Filing] = relationship(back_populates="chunks")


class FilingTable(Base):
    """A structured table extracted from a filing, kept queryable.

    ``columns`` is the best-effort header row; ``rows`` is a list-of-lists of
    cell strings (nulls preserved). Storing as JSONB means Table QA can index
    into / query cells with Postgres JSON operators instead of re-parsing text.
    """

    __tablename__ = "filing_tables"
    __table_args__ = (
        UniqueConstraint(
            "filing_id", "page_number", "table_index", name="uq_filing_table_pos"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filing_id: Mapped[int] = mapped_column(
        ForeignKey("filings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    # 0-based ordinal of the table within its page.
    table_index: Mapped[int] = mapped_column(Integer, nullable=False)
    n_rows: Mapped[int] = mapped_column(Integer, nullable=False)
    n_cols: Mapped[int] = mapped_column(Integer, nullable=False)
    columns: Mapped[list] = mapped_column(JSONB, nullable=False)
    rows: Mapped[list] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    filing: Mapped[Filing] = relationship(back_populates="tables")


class Transcript(Base):
    """An audio source (e.g., an earnings call) and its ASR metadata."""

    __tablename__ = "transcripts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="local_sample")
    audio_file_name: Mapped[str] = mapped_column(String(512), nullable=False)
    audio_file_path: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    # Whisper's detected language + the model that produced the transcript, so
    # results are reproducible/auditable.
    language: Mapped[str | None] = mapped_column(String(16))
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    model_name: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    segments: Mapped[list[TranscriptSegment]] = relationship(
        back_populates="transcript", cascade="all, delete-orphan"
    )


class TranscriptSegment(Base):
    """One timestamped span of transcribed speech."""

    __tablename__ = "transcript_segments"
    __table_args__ = (
        UniqueConstraint(
            "transcript_id", "segment_index", name="uq_transcript_segment_index"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    transcript_id: Mapped[int] = mapped_column(
        ForeignKey("transcripts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    segment_index: Mapped[int] = mapped_column(Integer, nullable=False)
    start_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    end_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    # Nullable: populated by the retrieval indexer (same as filing chunks).
    embedding: Mapped[list[float] | None] = mapped_column(Vector(_EMBEDDING_DIM))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    transcript: Mapped[Transcript] = relationship(back_populates="segments")
