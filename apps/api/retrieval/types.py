"""Shared result types for retrieval / QA.

These are Pydantic models (not bare dataclasses) because they *are* the QA
agent's output contract: CLAUDE.md requires every agent output to be validated
against a schema before it's handed on, and these double as the API response
models. Keeping them here (not in the endpoint module) lets the service layer
build and validate answers without importing FastAPI.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class Confidence(str, Enum):
    """Coarse confidence band attached to every answer."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"  # used together with sufficient=False


class QAPath(str, Enum):
    TABLE = "table"
    DOCUMENT = "document"


class Citation(BaseModel):
    """A pointer back to the exact evidence an answer was drawn from."""

    source_type: str = Field(description="'chunk' or 'table'")
    source_id: int = Field(description="filing_chunks.id or filing_tables.id")
    filing_id: int | None = None
    page_number: int | None = None
    # Retrieval similarity (chunks) — omitted/None for structured table hits.
    similarity: float | None = None


class Answer(BaseModel):
    """The full QA result: text + citations + confidence + sufficiency."""

    question: str
    ticker: str
    path: QAPath
    answer: str
    # False => retrieval didn't support an answer; `answer` states as much and
    # `citations` is empty. This is a first-class, valid outcome.
    sufficient: bool
    confidence: Confidence
    citations: list[Citation] = Field(default_factory=list)
    # Short note on why the router picked this path (useful for debugging/eval).
    router_reason: str | None = None

    @classmethod
    def insufficient(
        cls, question: str, ticker: str, path: QAPath, reason: str | None = None
    ) -> "Answer":
        """Build the canonical 'insufficient evidence' answer."""
        return cls(
            question=question,
            ticker=ticker,
            path=path,
            answer="Insufficient evidence in the retrieved sources to answer this question.",
            sufficient=False,
            confidence=Confidence.NONE,
            citations=[],
            router_reason=reason,
        )
