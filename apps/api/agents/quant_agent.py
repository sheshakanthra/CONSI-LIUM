"""quant_agent — a classical price-history forecasting signal (Phase 4).

This replaces the Phase 3 stub. It now:

  1. Ingests OHLC price history for the ticker through a small ``PriceDataSource``
     seam. We have no live market-data feed wired in yet, so the default source is
     a *deterministic synthetic* price series (same philosophy as Phase 1's
     generated sample filings). The seam is the important part: a real provider
     (Kite Connect, Alpha Vantage, …) implements the same ``get_ohlc`` method and
     drops in without touching the agent, the graph, or the synthesizer.

  2. Runs a lightweight, dependency-free classical forecaster over the closes:
     double (Holt) exponential smoothing for the trend, confirmed by a
     short/long simple-moving-average crossover and raw momentum. WHY classical
     and not an ML model: this is a *supporting* signal, the sample data is a
     random walk (so a heavy model would only overfit noise), and the whole point
     of the phase is a clean, explainable, swappable baseline — not alpha. Adding
     numpy/statsmodels/torch here would be unjustified weight (see
     docs/phase4-quant.md).

  3. Emits a structured ``QuantSignal`` with a real ``direction``, ``confidence``,
     ``horizon`` and plain-language ``reasoning`` — ``is_placeholder`` is now
     ``False``. The schema is a superset of the Phase 3 stub's, so the
     synthesizer's contract (``direction``, ``series``, ``is_placeholder``) still
     holds while the new fields let it note agreement/disagreement with the
     qualitative bull/bear thesis.

IMPORTANT: this is a supporting technical signal only. It is derived from price
history alone, on synthetic data, and is NOT investment advice.
"""

from __future__ import annotations

import hashlib
import math
import statistics
from enum import Enum
from typing import Protocol

from pydantic import BaseModel, Field

SYSTEM_PROMPT = """\
You are the Quant Agent. Given a ticker's OHLC price history, produce a
quantitative technical signal — direction (bullish/bearish/neutral), a calibrated
confidence, a forecast horizon, and short plain-language reasoning — using
transparent classical methods (moving-average crossover, exponential smoothing,
momentum). Report only what the price series supports; this is a supporting
signal, not investment advice.
"""

# How many future sessions the forecast projects. Also the label in ``horizon``.
_HORIZON_SESSIONS = 5
# How many sessions of history the synthetic source produces / the model reads.
_LOOKBACK_SESSIONS = 120
# Windows for the SMA crossover. Short reacts fast; long is the trend baseline.
_SMA_SHORT, _SMA_LONG = 10, 30
# Holt (double) exponential smoothing coefficients: level and trend learning
# rates. Modest values so a single spike doesn't flip the projected trend.
_ALPHA, _BETA = 0.3, 0.1


class QuantDirection(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class OHLCBar(BaseModel):
    """One session of price data. ``index`` is a session ordinal (0 = oldest).

    We keep this provider-agnostic (no real dates/tz): the synthetic source and a
    future Kite adapter both populate the same shape, so downstream code never
    learns where the bars came from.
    """

    index: int
    open: float
    high: float
    low: float
    close: float
    volume: float


class QuantSignal(BaseModel):
    """Quant agent output schema.

    A superset of the Phase 3 stub: ``direction``/``series``/``is_placeholder``
    are unchanged so the synthesizer contract holds, and ``confidence``,
    ``horizon`` and ``reasoning`` carry the real signal.
    """

    ticker: str
    direction: QuantDirection
    # Calibrated conviction in ``direction``, 0..1. Capped below 1.0 on purpose —
    # a price-only technical model should never claim near-certainty.
    confidence: float = Field(ge=0.0, le=1.0)
    # Human-readable forecast horizon, e.g. "5 trading sessions".
    horizon: str
    # Plain-language explanation of how the indicators produced the call.
    reasoning: str
    # Signed conviction (sign = direction, magnitude = confidence); handy for
    # charts/aggregation. 0.0 when neutral.
    score: float = Field(ge=-1.0, le=1.0)
    # The projected close path over the horizon, so a chart has something to draw.
    series: list[float]
    # Real signal now — the Phase 3 stub set this True.
    is_placeholder: bool = False
    note: str


# --------------------------------------------------------------------------- #
# Price-data seam                                                              #
# --------------------------------------------------------------------------- #
class PriceDataSource(Protocol):
    """The market-data seam. A real provider implements this and drops in.

    Kept async so a networked implementation (e.g. Kite Connect) fits without
    changing the agent, which already ``await``s it.
    """

    async def get_ohlc(self, ticker: str, lookback: int) -> list[OHLCBar]: ...


class SyntheticPriceSource:
    """A deterministic synthetic OHLC generator seeded by the ticker.

    WHY synthetic: no live feed is connected this phase, and committing real
    market data is neither reproducible nor licensable. Seeding off the ticker
    makes every run — tests, backtest, demo — reproducible for a given symbol,
    exactly like the Phase 1 sample filings.

    The path is a geometric random walk with a small symbol-dependent drift, so
    different tickers show different (but fixed) up/down tendencies rather than
    all looking identical. This is NOT a market model — it just yields a
    plausibly-shaped series for the forecaster to operate on.
    """

    def __init__(self, start_price: float = 100.0) -> None:
        self._start = start_price

    async def get_ohlc(self, ticker: str, lookback: int = _LOOKBACK_SESSIONS) -> list[OHLCBar]:
        return self.generate(ticker, lookback)

    def generate(self, ticker: str, lookback: int = _LOOKBACK_SESSIONS) -> list[OHLCBar]:
        """Pure, synchronous generator (also used directly by the backtest)."""
        seed = int(hashlib.sha256(ticker.encode()).hexdigest(), 16)
        rng = _Lcg(seed)

        # A tiny per-symbol drift in [-0.0015, +0.0015] per session, plus fixed
        # volatility. Deterministic in the seed so the series never changes.
        drift = ((seed % 1000) / 1000.0 - 0.5) * 0.003
        vol = 0.015

        bars: list[OHLCBar] = []
        price = self._start
        for i in range(lookback):
            # Gaussian-ish shock from two uniforms (Irwin–Hall, no numpy needed).
            shock = (rng.next_float() + rng.next_float() - 1.0) * vol
            ret = drift + shock
            open_ = price
            close = max(0.01, open_ * (1.0 + ret))
            high = max(open_, close) * (1.0 + rng.next_float() * vol * 0.5)
            low = min(open_, close) * (1.0 - rng.next_float() * vol * 0.5)
            volume = 1_000_000 * (0.7 + rng.next_float() * 0.6)
            bars.append(
                OHLCBar(
                    index=i,
                    open=round(open_, 2),
                    high=round(high, 2),
                    low=round(low, 2),
                    close=round(close, 2),
                    volume=round(volume, 0),
                )
            )
            price = close
        return bars


class _Lcg:
    """A tiny seeded linear-congruential PRNG (numpy-free, fully reproducible).

    Python's ``random`` would work, but a self-contained LCG keeps the synthetic
    source's output identical across interpreters/platforms — important because
    the tests assert on a signal derived from this exact series.
    """

    _MOD = 2**48
    _A = 25214903917
    _C = 11

    def __init__(self, seed: int) -> None:
        self._state = seed % self._MOD

    def next_float(self) -> float:
        self._state = (self._A * self._state + self._C) % self._MOD
        return self._state / self._MOD


# --------------------------------------------------------------------------- #
# Forecaster                                                                   #
# --------------------------------------------------------------------------- #
class Forecast(BaseModel):
    """The forecaster's raw quantitative output, before prose is attached."""

    direction: QuantDirection
    confidence: float
    score: float
    projected: list[float]
    short_sma: float
    long_sma: float
    momentum: float
    trend_per_session: float
    reasoning: str


def _sma(values: list[float], window: int) -> float:
    window = min(window, len(values))
    return statistics.fmean(values[-window:])


def _holt_forecast(closes: list[float], horizon: int) -> tuple[list[float], float]:
    """Double exponential smoothing (Holt). Returns (projected path, trend/step).

    Level + trend are smoothed jointly so the projection extrapolates the recent
    slope rather than the last noisy print. We return the per-session trend too
    because its sign/size feeds the direction and confidence logic.
    """
    if len(closes) < 2:
        last = closes[-1] if closes else 0.0
        return [last] * horizon, 0.0

    level = closes[0]
    trend = closes[1] - closes[0]
    for value in closes[1:]:
        prev_level = level
        level = _ALPHA * value + (1 - _ALPHA) * (level + trend)
        trend = _BETA * (level - prev_level) + (1 - _BETA) * trend

    projected = [round(level + step * trend, 2) for step in range(1, horizon + 1)]
    return projected, trend


def forecast_closes(closes: list[float], horizon: int = _HORIZON_SESSIONS) -> Forecast:
    """Run the classical baseline over a close series and produce a signal.

    Pure and side-effect-free so both the agent and the backtest call it. The
    call is a *majority vote* of three transparent indicators — SMA crossover,
    momentum, and the smoothed trend — with confidence scaled by how strongly
    they agree and how large the move is relative to the series' volatility.
    """
    short_sma = _sma(closes, _SMA_SHORT)
    long_sma = _sma(closes, _SMA_LONG)

    # Momentum over the long window (guard the divide).
    ref = closes[-min(_SMA_LONG, len(closes))]
    momentum = (closes[-1] - ref) / ref if ref else 0.0

    projected, trend = _holt_forecast(closes, horizon)

    # Per-session returns → volatility, used to judge whether the move is real
    # signal or just noise.
    returns = [
        (closes[i] - closes[i - 1]) / closes[i - 1]
        for i in range(1, len(closes))
        if closes[i - 1]
    ]
    vol = statistics.pstdev(returns) if len(returns) > 1 else 0.0

    # Three directional votes in {-1, 0, +1}.
    sma_vote = _sign(short_sma - long_sma)
    mom_vote = _sign(momentum)
    trend_vote = _sign(trend)
    votes = sma_vote + mom_vote + trend_vote  # -3..3
    net = _sign(votes)
    agreement = abs(votes) / 3.0  # 0, .33, .67, 1

    # How large is the move relative to typical session noise? tanh-bounded.
    strength = math.tanh(abs(momentum) / (2 * vol)) if vol > 0 else float(bool(momentum))

    if net > 0:
        direction = QuantDirection.BULLISH
    elif net < 0:
        direction = QuantDirection.BEARISH
    else:
        direction = QuantDirection.NEUTRAL

    if direction is QuantDirection.NEUTRAL:
        # Conviction here is that the series is range-bound: higher when the move
        # is small. Deliberately modest.
        confidence = round(0.25 + 0.15 * (1 - strength), 3)
    else:
        # Concurrence × magnitude, floored so a directional call is never near 0
        # and capped so a price-only model never claims certainty.
        confidence = round(min(0.95, 0.35 + 0.6 * agreement * max(strength, 0.25)), 3)

    score = round((1 if net > 0 else -1 if net < 0 else 0) * confidence, 3)

    reasoning = _explain(
        direction, short_sma, long_sma, momentum, trend, vol, agreement, projected
    )
    return Forecast(
        direction=direction,
        confidence=confidence,
        score=score,
        projected=projected,
        short_sma=round(short_sma, 2),
        long_sma=round(long_sma, 2),
        momentum=round(momentum, 4),
        trend_per_session=round(trend, 4),
        reasoning=reasoning,
    )


def _sign(x: float) -> int:
    return 1 if x > 0 else -1 if x < 0 else 0


def _explain(
    direction: QuantDirection,
    short_sma: float,
    long_sma: float,
    momentum: float,
    trend: float,
    vol: float,
    agreement: float,
    projected: list[float],
) -> str:
    cross = (
        "above" if short_sma > long_sma else "below" if short_sma < long_sma else "at"
    )
    slope = "rising" if trend > 0 else "falling" if trend < 0 else "flat"
    concur = {0.0: "no", 1 / 3: "weak", 2 / 3: "moderate", 1.0: "full"}[
        round(agreement * 3) / 3
    ]
    return (
        f"The {_SMA_SHORT}-session average ({short_sma:.2f}) sits {cross} the "
        f"{_SMA_LONG}-session average ({long_sma:.2f}); {_SMA_LONG}-session "
        f"momentum is {momentum:+.1%} and the smoothed trend is {slope}. "
        f"Indicators show {concur} concurrence (session volatility {vol:.2%}). "
        f"The {len(projected)}-session projection ends near {projected[-1]:.2f}, "
        f"implying a {direction.value} bias. Technical, price-only signal — not "
        f"investment advice."
    )


class QuantAgent:
    """Fetches price history and turns it into a structured technical signal.

    The data source is injected (defaulting to the synthetic generator) so a real
    provider can be supplied without changing the graph node that calls ``run``.
    """

    def __init__(
        self,
        source: PriceDataSource | None = None,
        horizon_sessions: int = _HORIZON_SESSIONS,
    ) -> None:
        self._source = source or SyntheticPriceSource()
        self._horizon = horizon_sessions

    async def run(self, ticker: str) -> QuantSignal:
        bars = await self._source.get_ohlc(ticker, _LOOKBACK_SESSIONS)
        closes = [b.close for b in bars]

        # No silent failure (CLAUDE.md): if the source returns too little to model,
        # emit an explicit low-confidence neutral signal rather than crashing the
        # graph or fabricating a call.
        if len(closes) < _SMA_LONG:
            return QuantSignal(
                ticker=ticker,
                direction=QuantDirection.NEUTRAL,
                confidence=0.1,
                horizon=self._horizon_label(),
                reasoning=(
                    f"Only {len(closes)} session(s) of price history available "
                    f"(need >= {_SMA_LONG}); cannot form a reliable technical view. "
                    "Neutral by default. Not investment advice."
                ),
                score=0.0,
                series=closes or [0.0],
                is_placeholder=False,
                note="Insufficient price history for a forecast.",
            )

        fc = forecast_closes(closes, self._horizon)
        return QuantSignal(
            ticker=ticker,
            direction=fc.direction,
            confidence=fc.confidence,
            horizon=self._horizon_label(),
            reasoning=fc.reasoning,
            score=fc.score,
            series=fc.projected,
            is_placeholder=False,
            note=(
                f"Classical forecast (Holt smoothing + {_SMA_SHORT}/{_SMA_LONG} SMA "
                f"crossover + momentum) over {len(closes)} synthetic sessions."
            ),
        )

    def _horizon_label(self) -> str:
        return f"{self._horizon} trading sessions"
