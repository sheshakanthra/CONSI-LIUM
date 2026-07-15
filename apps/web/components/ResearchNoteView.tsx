/**
 * The research note: thesis, fact-checked claims, quant signal, citations.
 *
 * WHY supported and disputed claims are separate, always-labelled sections —
 * and why the disputed section renders even when it's the *only* section: the
 * synthesizer partitions claims by the fact-checker's verdict deliberately
 * (synthesizer_agent.py), and that partition is the product. A note where every
 * claim was contradicted is a meaningful, honest result; presenting it as an
 * empty page would hide the fact-checker doing its job, which is the one thing
 * this project most wants visible.
 *
 * WHY the empty case says "no claims survived fact-checking" rather than "no
 * results": those are different findings and the distinction is the whole point.
 */
import type { Citation, ResearchNote } from "@/lib/schemas";

import { ClaimCard } from "./ClaimCard";
import { QuantPanel } from "./QuantPanel";

type ResearchNoteViewProps = {
  note: ResearchNote;
  onSelectCitation: (citation: Citation) => void;
  activeCitation: Citation | null;
};

function SectionHeading({
  children,
  count,
}: {
  children: React.ReactNode;
  count: number;
}) {
  return (
    <div className="flex items-baseline gap-2">
      <h2 className="text-xs font-medium uppercase tracking-widest text-neutral-500">
        {children}
      </h2>
      <span className="font-mono text-xs text-neutral-700">{count}</span>
    </div>
  );
}

export function ResearchNoteView({
  note,
  onSelectCitation,
  activeCitation,
}: ResearchNoteViewProps) {
  const supported = note.key_supported_claims;
  const disputed = note.key_disputed_or_unverifiable_claims;
  const nothingChecked = supported.length === 0 && disputed.length === 0;

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_20rem] lg:items-start">
      <div className="space-y-6">
        <section aria-labelledby="thesis-heading">
          <h2
            id="thesis-heading"
            className="text-xs font-medium uppercase tracking-widest text-neutral-500"
          >
            Thesis
          </h2>
          <p className="mt-2 text-sm leading-relaxed text-neutral-300">
            {note.thesis_summary}
          </p>
        </section>

        {nothingChecked && (
          <p className="rounded-lg border border-neutral-800 bg-neutral-950/40 p-4 text-sm text-neutral-500">
            No claims survived fact-checking for {note.ticker}. The bull and bear
            agents produced no evidence-backed claims — most often because this
            ticker&apos;s filings haven&apos;t been ingested and indexed.
          </p>
        )}

        {supported.length > 0 && (
          <section aria-labelledby="supported-heading" className="space-y-3">
            <SectionHeading count={supported.length}>
              <span id="supported-heading">Supported claims</span>
            </SectionHeading>
            {supported.map((claim, i) => (
              <ClaimCard
                key={`s-${i}`}
                claim={claim}
                onSelectCitation={onSelectCitation}
                activeCitation={activeCitation}
              />
            ))}
          </section>
        )}

        {disputed.length > 0 && (
          <section aria-labelledby="disputed-heading" className="space-y-3">
            <SectionHeading count={disputed.length}>
              <span id="disputed-heading">Disputed or unverifiable</span>
            </SectionHeading>
            <p className="text-xs leading-relaxed text-neutral-600">
              Flagged by the fact-checker and excluded from the core thesis.
            </p>
            {disputed.map((claim, i) => (
              <ClaimCard
                key={`d-${i}`}
                claim={claim}
                onSelectCitation={onSelectCitation}
                activeCitation={activeCitation}
              />
            ))}
          </section>
        )}
      </div>

      <div className="space-y-6">
        <QuantPanel signal={note.quant_signal} />

        {note.citations.length > 0 && (
          <section
            aria-labelledby="sources-heading"
            className="rounded-lg border border-neutral-800 bg-neutral-950/60 p-5"
          >
            <h2
              id="sources-heading"
              className="text-xs font-medium uppercase tracking-widest text-neutral-500"
            >
              Sources
            </h2>
            <p className="mt-1 text-xs text-neutral-600">
              De-duplicated evidence behind the supported claims.
            </p>
            <ul className="mt-3 space-y-1.5">
              {note.citations.map((citation) => (
                <li key={`${citation.source_type}-${citation.source_id}`}>
                  <button
                    type="button"
                    onClick={() => onSelectCitation(citation)}
                    className="w-full text-left font-mono text-xs text-neutral-500 transition-colors hover:text-accent"
                  >
                    {citation.source_type} · #{citation.source_id}
                    {citation.page_number != null && ` · p.${citation.page_number}`}
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </div>
  );
}
