"""quant_agent — PLACEHOLDER (Phase 4 will fill this in).

Returns a deterministic stub time-series signal so the graph and the synthesizer
have a well-typed quant input to consume now. It does NOT look at prices or the
filings yet — Phase 4 replaces the body with a real signal (e.g., momentum /
factor model over ingested market data). The output schema is designed so that
swap won't change the synthesizer's contract.

The stub is deterministic in the ticker (seeded) so tests are stable.
"""

from __future__ import annotations

import hashlib
from enum import Enum

from pydantic import BaseModel

SYSTEM_PROMPT = """\
You are the Quant Agent. Produce a quantitative signal (direction, score, and a
short series) for the given ticker. [Phase 3: stubbed — returns a placeholder
signal; Phase 4 will compute a real one from market data.]
"""


class QuantDirection(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class QuantSignal(BaseModel):
    """Quant agent output schema (stable across the Phase 4 swap)."""

    ticker: str
    direction: QuantDirection
    # -1.0..1.0; 0 for the neutral placeholder.
    score: float
    # A short synthetic series so downstream charts have something to render.
    series: list[float]
    is_placeholder: bool = True
    note: str


class QuantAgent:
    async def run(self, ticker: str) -> QuantSignal:
        # Deterministic pseudo-series seeded by the ticker (NOT a real signal).
        seed = int(hashlib.sha256(ticker.encode()).hexdigest(), 16)
        series = [round(((seed >> (i * 3)) % 100) / 100.0, 3) for i in range(8)]
        return QuantSignal(
            ticker=ticker,
            direction=QuantDirection.NEUTRAL,
            score=0.0,
            series=series,
            is_placeholder=True,
            note="Stub signal -- quant model lands in Phase 4.",
        )
