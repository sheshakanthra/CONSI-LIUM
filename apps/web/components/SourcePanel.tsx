"use client";

/**
 * The citation drill-down: a selected citation, resolved to real evidence.
 *
 * This panel is where the project's central claim stops being an assertion and
 * becomes checkable — "every claim traces to a source page/cell" is only true
 * if a reader can press the chip and *see the cell*. It renders whatever
 * /sources returns, verbatim: chunk text as-is, tables as a real grid with the
 * header intact (never flattened to prose — the same rule ingestion follows).
 *
 * WHY it fetches per selection instead of the note carrying evidence inline:
 * citations are pointers by design (see retrieval/sources.py), and a note can
 * cite the same chunk from many claims. Fetching on demand keeps the research
 * payload small and means the evidence shown is read from the DB at view time,
 * not a copy that travelled through the agent graph and could have drifted.
 */
import { useEffect, useState } from "react";

import { ApiError, fetchSource } from "@/lib/api";
import type { Citation, SourceDocument } from "@/lib/schemas";

type SourcePanelProps = {
  citation: Citation | null;
  onClose: () => void;
};

type FetchState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "success"; doc: SourceDocument }
  | { status: "error"; error: ApiError };

/** JSONB cells are `unknown`; render them without pretending they're strings. */
function cell(value: unknown): string {
  if (value == null) return "—";
  return typeof value === "string" ? value : String(value);
}

function TableView({ doc }: { doc: SourceDocument }) {
  if (!doc.table) return null;
  return (
    // Wide filing tables must scroll inside the panel, not blow out the page.
    <div className="overflow-x-auto rounded border border-neutral-800">
      <table className="w-full border-collapse text-left text-xs">
        <thead>
          <tr className="border-b border-neutral-800 bg-neutral-900/60">
            {doc.table.columns.map((col, i) => (
              <th
                key={i}
                className="whitespace-nowrap px-2.5 py-1.5 font-medium text-neutral-300"
              >
                {cell(col)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {doc.table.rows.map((row, r) => (
            <tr key={r} className="border-b border-neutral-900 last:border-0">
              {row.map((value, c) => (
                <td
                  key={c}
                  className="whitespace-nowrap px-2.5 py-1.5 font-mono text-neutral-400"
                >
                  {cell(value)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function SourcePanel({ citation, onClose }: SourcePanelProps) {
  const [state, setState] = useState<FetchState>({ status: "idle" });

  useEffect(() => {
    if (!citation) {
      setState({ status: "idle" });
      return;
    }
    // Same supersede-guard as useResearch: clicking chips quickly must not let
    // an earlier response paint over a later selection.
    const controller = new AbortController();
    setState({ status: "loading" });
    fetchSource(citation, controller.signal)
      .then((doc) => {
        if (!controller.signal.aborted) setState({ status: "success", doc });
      })
      .catch((err) => {
        if (controller.signal.aborted) return;
        setState({
          status: "error",
          error:
            err instanceof ApiError
              ? err
              : new ApiError("network", (err as Error)?.message ?? "Unknown error"),
        });
      });
    return () => controller.abort();
  }, [citation]);

  // Escape closes — standard dismissal affordance for an overlay panel.
  useEffect(() => {
    if (!citation) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [citation, onClose]);

  if (!citation) return null;

  return (
    <aside
      aria-label="Source evidence"
      className="fixed inset-y-0 right-0 z-20 flex w-full max-w-xl flex-col border-l border-neutral-800 bg-neutral-950 shadow-2xl"
    >
      <header className="flex items-start justify-between gap-4 border-b border-neutral-800 px-5 py-4">
        <div>
          <h2 className="text-xs font-medium uppercase tracking-widest text-neutral-500">
            Source evidence
          </h2>
          <p className="mt-1 font-mono text-xs text-neutral-400">
            {citation.source_type} · id {citation.source_id}
            {citation.page_number != null && ` · page ${citation.page_number}`}
            {/* Similarity is only meaningful for vector hits; tables have none. */}
            {citation.similarity != null &&
              ` · similarity ${citation.similarity.toFixed(3)}`}
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close source panel"
          className="rounded border border-neutral-800 px-2 py-1 text-xs text-neutral-400 transition-colors hover:border-neutral-600 hover:text-neutral-200"
        >
          Esc
        </button>
      </header>

      <div className="flex-1 overflow-y-auto px-5 py-4">
        {state.status === "loading" && (
          <p className="text-sm text-neutral-500">Resolving source…</p>
        )}

        {state.status === "error" && (
          <div className="rounded border border-rose-500/40 bg-rose-500/5 p-3">
            <p className="text-sm text-rose-400">
              {state.error.kind === "not_found"
                ? "This citation does not resolve to a stored source."
                : "Could not load this source."}
            </p>
            <p className="mt-1 text-xs text-neutral-500">{state.error.message}</p>
          </div>
        )}

        {state.status === "success" && (
          <>
            <dl className="mb-4 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-xs">
              <dt className="text-neutral-600">Filing</dt>
              <dd className="font-mono text-neutral-400">
                {state.doc.file_name}
              </dd>
              {state.doc.company && (
                <>
                  <dt className="text-neutral-600">Company</dt>
                  <dd className="text-neutral-400">{state.doc.company}</dd>
                </>
              )}
              {state.doc.ticker && (
                <>
                  <dt className="text-neutral-600">Ticker</dt>
                  <dd className="font-mono text-neutral-400">
                    {state.doc.ticker}
                  </dd>
                </>
              )}
            </dl>

            {state.doc.chunk && (
              <p className="whitespace-pre-wrap rounded border border-neutral-800 bg-neutral-900/40 p-3 text-sm leading-relaxed text-neutral-300">
                {state.doc.chunk.text}
              </p>
            )}
            {state.doc.table && <TableView doc={state.doc} />}
          </>
        )}
      </div>
    </aside>
  );
}
