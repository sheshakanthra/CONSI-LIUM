"""Table QA: answer a numeric question from structured ``filing_tables``.

This is the payoff of keeping tables structured in Phase 1: instead of hoping a
number survives inside a text chunk, we look it up by (metric row, period
column) and return the exact cell — with a citation to the table id and page.

Matching is deliberately simple and explainable:
  * pick the row whose metric label best overlaps the question's words
    (with a few finance synonyms), and
  * pick the column whose header best overlaps the question; if the question
    names no period, default to the first data column (the most recent one).

If no metric row matches, we return "insufficient evidence" rather than guess.
A future upgrade could use fuzzy/semantic cell matching, but the brief asks for
a simple structured path first.
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ingestion.models import Filing, FilingTable
from retrieval.types import Answer, Citation, Confidence, QAPath

# Map a user word -> the row-label words it should also match.
_SYNONYMS: dict[str, set[str]] = {
    "sales": {"revenue"},
    "turnover": {"revenue"},
    "pat": {"net", "profit"},
    "income": {"profit"},
    "growth": {"yoy"},
}


def _tokens(text: str | None) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", (text or "").lower()))


def _expand(question_tokens: set[str]) -> set[str]:
    expanded = set(question_tokens)
    for tok in question_tokens:
        expanded |= _SYNONYMS.get(tok, set())
    return expanded


def _best_row(q: set[str], columns: list, rows: list[list]) -> tuple[int, int] | None:
    """Return (row_index, overlap) for the metric row best matching the question."""
    best: tuple[int, int] | None = None
    for i, row in enumerate(rows):
        if not row:
            continue
        overlap = len(_tokens(str(row[0])) & q)
        if overlap and (best is None or overlap > best[1]):
            best = (i, overlap)
    return best


def _best_column(q: set[str], columns: list) -> int:
    """Return the data-column index best matching the question (default: 1)."""
    best_idx, best_overlap = 1, 0  # col 0 is the metric label; 1 = first period
    for j in range(1, len(columns)):
        overlap = len(_tokens(str(columns[j])) & q)
        if overlap > best_overlap:
            best_idx, best_overlap = j, overlap
    return best_idx if len(columns) > 1 else 0


async def answer_from_tables(
    session: AsyncSession, ticker: str, question: str, router_reason: str | None = None
) -> Answer:
    """Answer ``question`` for ``ticker`` from structured tables."""
    tables = (
        await session.execute(
            select(FilingTable)
            .join(Filing, Filing.id == FilingTable.filing_id)
            .where(Filing.ticker == ticker)
        )
    ).scalars().all()

    if not tables:
        return Answer.insufficient(question, ticker, QAPath.TABLE, router_reason)

    q = _expand(_tokens(question))

    # Search every table; keep the strongest metric-row match across all of them.
    best = None  # (overlap, table, row_index, col_index)
    for table in tables:
        hit = _best_row(q, table.columns, table.rows)
        if hit is None:
            continue
        row_idx, overlap = hit
        col_idx = _best_column(q, table.columns)
        if best is None or overlap > best[0]:
            best = (overlap, table, row_idx, col_idx)

    if best is None:
        return Answer.insufficient(question, ticker, QAPath.TABLE, router_reason)

    _overlap, table, row_idx, col_idx = best
    row = table.rows[row_idx]
    metric_label = str(row[0]).strip()
    value = str(row[col_idx]).strip() if col_idx < len(row) and row[col_idx] is not None else ""
    column_label = str(table.columns[col_idx]).strip() if col_idx < len(table.columns) else ""

    if not value:
        return Answer.insufficient(question, ticker, QAPath.TABLE, router_reason)

    answer_text = (
        f"{metric_label} ({column_label}) is {value}."
        if column_label
        else f"{metric_label} is {value}."
    )
    return Answer(
        question=question,
        ticker=ticker,
        path=QAPath.TABLE,
        answer=answer_text,
        sufficient=True,
        # Structured cell lookups are exact when a metric row matched.
        confidence=Confidence.HIGH,
        citations=[
            Citation(
                source_type="table",
                source_id=table.id,
                filing_id=table.filing_id,
                page_number=table.page_number,
            )
        ],
        router_reason=router_reason,
    )
