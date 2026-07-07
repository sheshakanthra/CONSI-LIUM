"""Unit tests for the Phase 4 quant agent.

These are DELIBERATELY offline: the quant agent reads a synthetic price source,
not the DB or an LLM, so unlike test_agents.py these need no Postgres and are not
marked ``integration``. They assert the output schema is well-formed and — the
whole point of Phase 4 — that it is no longer a placeholder.
"""

from __future__ import annotations

import pytest

from agents.quant_agent import (
    OHLCBar,
    QuantAgent,
    QuantDirection,
    QuantSignal,
    SyntheticPriceSource,
    forecast_closes,
)

_TICKER = "ACME"


async def test_quant_signal_is_well_formed_and_not_a_placeholder():
    signal = await QuantAgent().run(_TICKER)

    assert isinstance(signal, QuantSignal)
    assert signal.ticker == _TICKER
    # The Phase 4 deliverable: real values, no longer a stub.
    assert signal.is_placeholder is False
    assert signal.direction in set(QuantDirection)
    assert 0.0 <= signal.confidence <= 1.0
    assert -1.0 <= signal.score <= 1.0
    assert signal.horizon.strip()
    assert signal.reasoning.strip()
    assert len(signal.series) > 0
    assert all(isinstance(x, float) for x in signal.series)


async def test_score_sign_matches_direction():
    signal = await QuantAgent().run(_TICKER)
    if signal.direction is QuantDirection.BULLISH:
        assert signal.score > 0
    elif signal.direction is QuantDirection.BEARISH:
        assert signal.score < 0
    else:
        assert signal.score == 0.0


async def test_signal_is_deterministic_for_a_ticker():
    a = await QuantAgent().run(_TICKER)
    b = await QuantAgent().run(_TICKER)
    assert a.model_dump() == b.model_dump()


def test_synthetic_source_shape_and_reproducibility():
    src = SyntheticPriceSource()
    bars = src.generate(_TICKER, lookback=60)
    assert len(bars) == 60
    assert all(isinstance(b, OHLCBar) for b in bars)
    # high >= low, and both bracket the open/close within the bar.
    for b in bars:
        assert b.high >= b.low
        assert b.high >= max(b.open, b.close) - 1e-6
        assert b.low <= min(b.open, b.close) + 1e-6
    # Same ticker -> identical series (seeded).
    assert [b.close for b in bars] == [b.close for b in src.generate(_TICKER, 60)]


def test_forecast_detects_a_clear_uptrend():
    closes = [100.0 + i for i in range(50)]  # strictly rising
    fc = forecast_closes(closes)
    assert fc.direction is QuantDirection.BULLISH
    assert fc.projected[-1] > closes[-1]


def test_forecast_detects_a_clear_downtrend():
    closes = [100.0 - i for i in range(50)]  # strictly falling
    fc = forecast_closes(closes)
    assert fc.direction is QuantDirection.BEARISH


async def test_insufficient_history_yields_neutral_not_crash():
    class ShortSource:
        async def get_ohlc(self, ticker: str, lookback: int) -> list[OHLCBar]:
            return [
                OHLCBar(index=i, open=100, high=101, low=99, close=100, volume=1)
                for i in range(5)
            ]

    signal = await QuantAgent(source=ShortSource()).run(_TICKER)
    assert signal.direction is QuantDirection.NEUTRAL
    assert signal.is_placeholder is False
    assert signal.confidence <= 0.2
