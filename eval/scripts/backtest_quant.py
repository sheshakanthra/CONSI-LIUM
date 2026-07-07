"""Walk-forward backtest for the quant forecaster (Phase 4).

Runs the classical forecaster (agents.quant_agent.forecast_closes) over the
synthetic price history in a *walk-forward* fashion: at each session t (after a
warm-up), fit only on closes[:t] and forecast session t+1, then compare the
1-session-ahead prediction against the realised close. No look-ahead — the model
never sees the point it is scoring.

Reported metrics:
  * Directional accuracy — did we get up/down right? (the metric that matters for
    a direction signal) plus a naive "always-up" baseline for context.
  * MAE / RMSE / MAPE — magnitude error of the 1-session point forecast.

WHY this exists / how to read it: the sample series is a near-random walk with a
tiny drift, so directional accuracy hovering around ~50% is EXPECTED and honest —
the point of the harness is the methodology (no look-ahead, baseline comparison,
reproducible), so a real data source can be dropped into ``SyntheticPriceSource``'s
place and measured the same way. See docs/phase4-quant.md. Not investment advice.

Run:  python eval/scripts/backtest_quant.py [TICKER ...]
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

# Make the API package importable when this file is run directly (it lives in
# eval/scripts, outside apps/api where the agents package sits).
_API = Path(__file__).resolve().parents[2] / "apps" / "api"
if str(_API) not in sys.path:
    sys.path.insert(0, str(_API))

from agents.quant_agent import (  # noqa: E402
    QuantDirection,
    SyntheticPriceSource,
    forecast_closes,
)

_WARMUP = 40  # need enough history for the long SMA before the first forecast.
_DEFAULT_TICKERS = ["ACME", "GLOBEX", "INITECH"]


def backtest_ticker(ticker: str, warmup: int = _WARMUP) -> dict[str, float]:
    """Walk-forward 1-session-ahead backtest for a single ticker."""
    closes = [b.close for b in SyntheticPriceSource().generate(ticker)]

    n_dir_correct = n_dir_total = 0
    n_up_actual = 0
    abs_errs: list[float] = []
    sq_errs: list[float] = []
    pct_errs: list[float] = []

    for t in range(warmup, len(closes) - 1):
        history = closes[:t + 1]
        actual_next = closes[t + 1]
        fc = forecast_closes(history, horizon=1)
        pred_next = fc.projected[0]

        # Point-error metrics (skip when direction is neutral? no — the point
        # forecast exists regardless of the categorical call).
        err = pred_next - actual_next
        abs_errs.append(abs(err))
        sq_errs.append(err * err)
        if actual_next:
            pct_errs.append(abs(err / actual_next))

        # Directional metric: compare predicted vs actual move sign. Neutral
        # calls are counted as a miss unless the market was genuinely flat.
        actual_move = _sign(actual_next - closes[t])
        if actual_move > 0:
            n_up_actual += 1
        pred_move = {
            QuantDirection.BULLISH: 1,
            QuantDirection.BEARISH: -1,
            QuantDirection.NEUTRAL: 0,
        }[fc.direction]
        n_dir_total += 1
        if pred_move == actual_move:
            n_dir_correct += 1

    n = len(abs_errs) or 1
    return {
        "sessions_scored": float(n_dir_total),
        "directional_accuracy": n_dir_correct / (n_dir_total or 1),
        "naive_up_rate": n_up_actual / (n_dir_total or 1),
        "mae": sum(abs_errs) / n,
        "rmse": math.sqrt(sum(sq_errs) / n),
        "mape": (sum(pct_errs) / len(pct_errs)) if pct_errs else float("nan"),
    }


def _sign(x: float) -> int:
    return 1 if x > 0 else -1 if x < 0 else 0


def main(tickers: list[str]) -> None:
    print("Quant forecaster walk-forward backtest (synthetic data)")
    print("=" * 68)
    print(
        f"{'ticker':<10}{'scored':>8}{'dir.acc':>10}{'naive-up':>10}"
        f"{'MAE':>10}{'RMSE':>10}{'MAPE':>10}"
    )
    print("-" * 68)
    for ticker in tickers:
        m = backtest_ticker(ticker)
        print(
            f"{ticker:<10}{int(m['sessions_scored']):>8}"
            f"{m['directional_accuracy']:>9.1%}{m['naive_up_rate']:>10.1%}"
            f"{m['mae']:>10.3f}{m['rmse']:>10.3f}{m['mape']:>9.2%}"
        )
    print("-" * 68)
    print(
        "Directional accuracy near ~50% is expected on this near-random-walk "
        "synthetic\nseries — the harness measures methodology, not alpha. "
        "Not investment advice."
    )


if __name__ == "__main__":
    main(sys.argv[1:] or _DEFAULT_TICKERS)
