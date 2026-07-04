"""Query router: structured-number question -> table path, else document path.

WHY a heuristic first: per the brief, start cheap. A keyword test over a curated
set of financial-metric terms is transparent, zero-latency, and good enough to
separate "what was revenue in Q1?" (a cell lookup) from "what did the board
say?" (prose). The seam is intentionally a single function returning a
``QAPath`` so it can later be swapped for a zero-shot classifier (e.g., a small
cross-encoder or an LLM call) without touching callers.

Note we deliberately EXCLUDE words like "dividend" — a question about a dividend
*recommendation* is narrative, not a number to pull from a table.
"""

from __future__ import annotations

import re

from retrieval.types import QAPath

# Terms that signal the answer is a structured figure living in a table.
_METRIC_TERMS: frozenset[str] = frozenset(
    {
        "revenue",
        "sales",
        "turnover",
        "ebitda",
        "margin",
        "margins",
        "profit",
        "pat",
        "eps",
        "earnings",
        "income",
        "yoy",
        "growth",
    }
)
# Multi-word cues checked as substrings.
_METRIC_PHRASES: tuple[str, ...] = (
    "net profit",
    "net income",
    "earnings per share",
    "year over year",
    "year-on-year",
    "how much",
)


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def route(question: str) -> tuple[QAPath, str]:
    """Return the chosen path and a short human-readable reason."""
    lowered = question.lower()
    hits = _tokens(question) & _METRIC_TERMS
    phrase_hits = [p for p in _METRIC_PHRASES if p in lowered]

    if hits or phrase_hits:
        cues = ", ".join(sorted(hits) + phrase_hits)
        return QAPath.TABLE, f"matched financial-metric cue(s): {cues}"
    return QAPath.DOCUMENT, "no structured-number cue; treating as narrative"
