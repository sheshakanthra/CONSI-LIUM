/**
 * Minimal inline-SVG sparkline for the quant agent's projected close path.
 *
 * WHY hand-rolled instead of a charting library: CLAUDE.md locks the stack and
 * says not to swap or add libraries silently. Recharts/Chart.js would add a
 * sizeable client bundle to draw a single unlabelled polyline of ~5 points —
 * unjustified weight, the same reasoning that kept numpy out of the quant agent
 * (see docs/phase4-quant.md). If real OHLC history and interactive charts land
 * later, that's the moment to propose a chart dependency, not now.
 *
 * It is intentionally decorative-but-honest: no axes, because the series is a
 * short synthetic projection and axes would imply a precision it doesn't have.
 * The numeric truth lives in the QuantPanel's text next to it.
 */

type SparklineProps = {
  series: number[];
  /** Direction drives the stroke colour so the glyph agrees with the verdict. */
  direction: "bullish" | "bearish" | "neutral";
  className?: string;
};

const STROKE: Record<SparklineProps["direction"], string> = {
  bullish: "#00ffcc",
  bearish: "#fb7185",
  neutral: "#a3a3a3",
};

const WIDTH = 240;
const HEIGHT = 56;
const PAD = 4;

export function Sparkline({ series, direction, className }: SparklineProps) {
  // Two points are the minimum for a line; anything less isn't a trend.
  if (series.length < 2) return null;

  const min = Math.min(...series);
  const max = Math.max(...series);
  // A flat series would divide by zero — render it down the middle instead.
  const span = max - min || 1;

  const points = series.map((value, i) => {
    const x = PAD + (i / (series.length - 1)) * (WIDTH - PAD * 2);
    // SVG y grows downward; invert so a rising close renders as a rising line.
    const y = PAD + (1 - (value - min) / span) * (HEIGHT - PAD * 2);
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  });

  const stroke = STROKE[direction];

  return (
    <svg
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      className={className}
      role="img"
      aria-label={`Projected close path, ${direction}, ${series.length} sessions`}
      preserveAspectRatio="none"
    >
      {/* Faded fill under the line: gives the glyph body without implying a scale. */}
      <polygon
        points={`${PAD},${HEIGHT - PAD} ${points.join(" ")} ${WIDTH - PAD},${HEIGHT - PAD}`}
        fill={stroke}
        fillOpacity={0.08}
      />
      <polyline
        points={points.join(" ")}
        fill="none"
        stroke={stroke}
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
