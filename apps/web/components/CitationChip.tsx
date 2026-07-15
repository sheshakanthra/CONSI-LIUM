/**
 * A clickable citation pointer.
 *
 * WHY a button and not a link: resolving a citation opens an in-page evidence
 * panel; it doesn't navigate. Using an anchor would lie to assistive tech and
 * hand users a browser back-button that does nothing.
 *
 * The chip shows the *pointer* (kind, page, id) rather than a preview of the
 * text. That's deliberate — it keeps the note scannable and makes the act of
 * checking evidence an explicit choice, which is what "auditable" means here.
 */
import type { Citation } from "@/lib/schemas";

type CitationChipProps = {
  citation: Citation;
  onSelect: (citation: Citation) => void;
  isActive?: boolean;
};

export function CitationChip({
  citation,
  onSelect,
  isActive = false,
}: CitationChipProps) {
  // Page is the useful human coordinate; the id is the exact one. Show page
  // when we have it, and always keep the id as the tiebreaker/debug handle.
  const label =
    citation.page_number != null
      ? `${citation.source_type} · p.${citation.page_number}`
      : `${citation.source_type} · #${citation.source_id}`;

  return (
    <button
      type="button"
      onClick={() => onSelect(citation)}
      aria-pressed={isActive}
      title={`Open source: ${citation.source_type} id ${citation.source_id}`}
      className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 font-mono text-[11px] transition-colors ${
        isActive
          ? "border-accent/60 bg-accent/10 text-accent"
          : "border-neutral-700 text-neutral-400 hover:border-accent/40 hover:text-accent"
      }`}
    >
      {label}
    </button>
  );
}
