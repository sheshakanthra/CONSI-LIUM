/**
 * The quant agent's technical signal.
 *
 * WHY this panel sits apart from the claims and is styled as a sidebar rather
 * than a headline: the quant signal is a *supporting* input, not the thesis. It
 * is derived from price history alone (currently synthetic — see
 * docs/phase4-quant.md), so giving it equal visual weight to fact-checked,
 * cited claims would misrepresent the pipeline. The agent's own `note` and the
 * not-investment-advice disclaimer are rendered, never dropped, for the same
 * reason.
 */
import type { QuantSignal } from "@/lib/schemas";

import { Sparkline } from "./Sparkline";

const DIRECTION_STYLE: Record<QuantSignal["direction"], string> = {
  bullish: "text-accent",
  bearish: "text-rose-400",
  neutral: "text-neutral-400",
};

export function QuantPanel({ signal }: { signal: QuantSignal }) {
  return (
    <section
      aria-labelledby="quant-heading"
      className="rounded-lg border border-neutral-800 bg-neutral-950/60 p-5"
    >
      <div className="flex items-baseline justify-between gap-3">
        <h2
          id="quant-heading"
          className="text-xs font-medium uppercase tracking-widest text-neutral-500"
        >
          Quant signal
        </h2>
        {/* If the stub ever comes back, say so plainly rather than passing it
            off as a real signal. */}
        {signal.is_placeholder && (
          <span className="rounded border border-amber-500/40 px-1.5 py-0.5 text-[10px] uppercase tracking-wider text-amber-400">
            placeholder
          </span>
        )}
      </div>

      <div className="mt-3 flex items-baseline gap-3">
        <span
          className={`text-2xl font-semibold tracking-tight ${DIRECTION_STYLE[signal.direction]}`}
        >
          {signal.direction}
        </span>
        <span className="text-sm text-neutral-500">
          {(signal.confidence * 100).toFixed(0)}% confidence
        </span>
      </div>

      <p className="mt-1 text-xs text-neutral-500">over {signal.horizon}</p>

      <Sparkline
        series={signal.series}
        direction={signal.direction}
        className="mt-4 h-14 w-full"
      />

      <p className="mt-4 text-sm leading-relaxed text-neutral-400">
        {signal.reasoning}
      </p>

      <p className="mt-4 border-t border-neutral-800/80 pt-3 text-xs leading-relaxed text-neutral-600">
        {signal.note}
      </p>
    </section>
  );
}
