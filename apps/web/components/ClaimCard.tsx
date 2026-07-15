/**
 * One fact-checked claim + its evidence.
 *
 * WHY the verdict label is rendered as a hard, colour-coded badge and never
 * omitted: the synthesizer's core guarantee is that a claim's status is a
 * property of the graph — SUPPORTED claims are the thesis, CONTRADICTED and
 * UNVERIFIABLE ones are surfaced as disputed, never quietly presented as fact
 * (see synthesizer_agent.py). A UI that dropped or softened the label would
 * break that guarantee at the last mile, which is the one place it matters —
 * in front of the reader.
 *
 * WHY a claim with no citations still renders (with an explicit "no evidence"
 * marker) rather than being hidden: an UNVERIFIABLE claim legitimately has no
 * supporting evidence, and hiding it would make the note look cleaner than the
 * pipeline's actual findings.
 */
import type { Citation, NoteClaim } from "@/lib/schemas";

import { CitationChip } from "./CitationChip";

const LABEL_STYLE: Record<NoteClaim["label"], string> = {
  SUPPORTED: "border-accent/40 bg-accent/10 text-accent",
  CONTRADICTED: "border-rose-500/40 bg-rose-500/10 text-rose-400",
  UNVERIFIABLE: "border-amber-500/40 bg-amber-500/10 text-amber-400",
};

const STANCE_STYLE: Record<NoteClaim["stance"], string> = {
  bull: "border-neutral-700 text-neutral-400",
  bear: "border-neutral-700 text-neutral-400",
};

type ClaimCardProps = {
  claim: NoteClaim;
  onSelectCitation: (citation: Citation) => void;
  activeCitation: Citation | null;
};

function isSame(a: Citation, b: Citation | null) {
  return (
    b != null && a.source_type === b.source_type && a.source_id === b.source_id
  );
}

export function ClaimCard({
  claim,
  onSelectCitation,
  activeCitation,
}: ClaimCardProps) {
  return (
    <article className="rounded-lg border border-neutral-800 bg-neutral-950/40 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={`rounded border px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider ${LABEL_STYLE[claim.label]}`}
        >
          {claim.label}
        </span>
        <span
          className={`rounded border px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider ${STANCE_STYLE[claim.stance]}`}
        >
          {claim.stance}
        </span>
      </div>

      <p className="mt-3 text-sm leading-relaxed text-neutral-200">
        {claim.text}
      </p>

      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        {claim.citations.length > 0 ? (
          claim.citations.map((citation) => (
            <CitationChip
              key={`${citation.source_type}-${citation.source_id}`}
              citation={citation}
              onSelect={onSelectCitation}
              isActive={isSame(citation, activeCitation)}
            />
          ))
        ) : (
          <span className="font-mono text-[11px] text-neutral-600">
            no independent evidence found
          </span>
        )}
      </div>
    </article>
  );
}
