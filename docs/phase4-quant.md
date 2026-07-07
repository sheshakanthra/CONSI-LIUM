# Phase 4 — Quant Signal (classical price forecasting)

> Design note for the quant phase. Per CLAUDE.md, each phase ships a short
> markdown note capturing the design decisions — these double as interview
> talking points.

> **Not investment advice.** The quant signal is a *supporting* technical
> indicator derived from price history alone, computed on **synthetic** data. It
> is not a recommendation to buy or sell anything.

## What this phase delivers

`apps/api/agents/quant_agent.py` graduates from a Phase 3 placeholder stub to a
real, self-contained forecasting signal:

1. **OHLC ingestion behind a seam** — a `PriceDataSource` protocol with a default
   `SyntheticPriceSource`. A real feed (Kite Connect, Alpha Vantage, …) drops in
   by implementing the same `get_ohlc` and is passed to `QuantAgent(source=...)`;
   nothing else in the graph changes.
2. **A classical forecaster** — Holt (double) exponential smoothing for the
   trend, confirmed by a short/long SMA crossover and raw momentum, combined by a
   transparent majority vote.
3. **A structured `QuantSignal`** — real `direction`, `confidence`, `horizon`,
   and plain-language `reasoning`; `is_placeholder` is now `False`.
4. **Synthesizer wiring** — the synthesizer explicitly states whether the quant
   signal **agrees or disagrees** with the qualitative bull/bear thesis.
5. **A backtest** (`eval/scripts/backtest_quant.py`) and **unit tests**
   (`apps/api/tests/test_quant_agent.py`).

Run it:

```bash
python eval/scripts/backtest_quant.py                 # walk-forward metrics
cd apps/api && pytest tests/test_quant_agent.py -v    # offline schema tests
```

## Why synthetic price data (for now)

No live market-data API is connected this phase, and committing real quotes is
neither reproducible nor cleanly licensable. Consistent with Phase 1's synthetic
sample filings, `SyntheticPriceSource` generates a **deterministic** geometric
random walk seeded by the ticker (a self-contained LCG, so the series is
identical across platforms). Every run — test, backtest, demo — sees the same
series for a given symbol. This is a stand-in shaped like price data, **not** a
market model.

The seam is the point: because ingestion sits behind `PriceDataSource`, swapping
in a real provider later touches exactly one class and leaves the forecaster, the
graph node, the schema, and the synthesizer untouched.

## Why a classical forecaster (not ML)

- **It's a supporting signal, not alpha.** The differentiator of this project is
  the fact-checked qualitative pipeline; quant corroborates or dissents. A heavy
  model would add weight and opacity for no real gain here.
- **The data is a near-random walk.** An ML model would only overfit noise, and
  its backtest would flatter a method that has no edge.
- **Explainability.** Holt smoothing + SMA crossover + momentum each contribute a
  legible vote, so `reasoning` is a true account of the call, not a post-hoc
  rationalisation of a black box.
- **No new dependencies.** The whole forecaster is `math`/`statistics` only — no
  numpy/pandas/statsmodels/torch, keeping the image lean (same discipline as
  choosing fastembed over torch in Phase 2).

### How the call is formed

Three directional votes in `{-1, 0, +1}` — SMA crossover (short vs long),
momentum sign, smoothed-trend sign — are summed. The majority sets `direction`.
`confidence` scales with (a) how strongly the three concur and (b) the size of
the move relative to the series' own volatility (a `tanh`-bounded ratio), and is
**capped at 0.95** — a price-only model should never claim near-certainty.
`series` is the projected close path over the horizon so a chart has something to
draw.

## Agreement with the qualitative thesis

The synthesizer reduces the fact-checked bull/bear balance to a single lean and
compares it to the quant direction, emitting one of *agree / disagree / no strong
signal*. A **disagreement is surfaced, not smoothed over** — when the price trend
and the fundamental narrative point opposite ways, that tension is exactly what a
reader needs to see.

## Backtest & metrics

`eval/scripts/backtest_quant.py` runs a **walk-forward** 1-session-ahead
evaluation: at each session it fits only on prior closes and forecasts the next —
no look-ahead. It reports:

- **Directional accuracy** vs a naive *always-up* baseline.
- **MAE / RMSE / MAPE** of the point forecast.

Representative output:

```
ticker      scored   dir.acc  naive-up       MAE      RMSE      MAPE
ACME            79    53.2%     53.2%     0.682     0.853    0.64%
GLOBEX          79    46.8%     46.8%     0.494     0.613    0.55%
INITECH         79    46.8%     48.1%     0.611     0.808    0.66%
```

Directional accuracy hovering around ~50% is **expected and honest** on a
near-random-walk series — there is no edge to find in noise, and the harness is
built to say so rather than to manufacture a number. The value is the
methodology: no look-ahead, a baseline to beat, and reproducibility, so a real
data source can be plugged in and measured the same way.

## Limitations (explicit)

- Synthetic data → the *magnitude* metrics describe the generator, not any real
  market; treat them as a wiring check, not a performance claim.
- Price-only → the signal ignores fundamentals, news, and regime shifts by
  design; it exists to *corroborate or dissent from* the qualitative thesis.
- Linear extrapolation → Holt projects the recent slope forward, so it lags
  turning points and has no notion of mean reversion or support/resistance.
- **Supporting signal only — not investment advice.**

## "Done" checklist (CLAUDE.md)

- [x] Runs end-to-end in the graph (`quant` node → synthesizer references it).
- [x] Tests: `apps/api/tests/test_quant_agent.py` (schema well-formed, no longer
      a placeholder) + updated assertions in `tests/test_agents.py`.
- [x] This design note.
