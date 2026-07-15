"use client";

/**
 * The research dashboard — Phase 6's deliverable.
 *
 * WHY this is a client component and not a server component with a server-side
 * fetch: a research run is user-initiated, slow (a full agent graph over live
 * LLM calls), abortable, and drives an interactive evidence panel. Rendering it
 * on the server would mean a blocking navigation per ticker and would make the
 * supersede/abort guard in `useResearch` impossible. The API is also reached
 * from the browser by design (see NEXT_PUBLIC_API_BASE_URL in .env.example).
 *
 * This page owns exactly two pieces of state — the research request and the
 * selected citation — and hands everything else to presentational components.
 */
import { useCallback, useState } from "react";

import { ErrorState } from "@/components/ErrorState";
import { ResearchNoteView } from "@/components/ResearchNoteView";
import { SourcePanel } from "@/components/SourcePanel";
import { TickerForm } from "@/components/TickerForm";
import type { Citation } from "@/lib/schemas";
import { useResearch } from "@/lib/useResearch";

export default function DashboardPage() {
  const { state, run } = useResearch();
  const [activeCitation, setActiveCitation] = useState<Citation | null>(null);

  const handleRun = useCallback(
    (ticker: string) => {
      // A new run invalidates the old note, so any open evidence panel is now
      // pointing at the previous ticker's source. Close it rather than leave a
      // stale citation on screen next to fresh results.
      setActiveCitation(null);
      void run(ticker);
    },
    [run],
  );

  const closePanel = useCallback(() => setActiveCitation(null), []);

  return (
    <main className="mx-auto max-w-6xl px-6 py-10">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <span className="text-xs font-medium uppercase tracking-[0.2em] text-neutral-600">
            Consilium
          </span>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight text-neutral-100">
            Research desk
          </h1>
          <p className="mt-1 text-sm text-neutral-500">
            Bull and bear agents argue; a fact-checker independently re-verifies
            every claim. Only what survives is shown.
          </p>
        </div>
        <TickerForm onSubmit={handleRun} isLoading={state.status === "loading"} />
      </header>

      <div className="mt-8">
        {state.status === "idle" && (
          <p className="rounded-lg border border-dashed border-neutral-800 p-8 text-center text-sm text-neutral-600">
            Enter a ticker to run the agent graph.
          </p>
        )}

        {state.status === "loading" && (
          <div className="rounded-lg border border-neutral-800 bg-neutral-950/40 p-8 text-center">
            <p className="text-sm text-neutral-400">
              Running the agent graph for{" "}
              <span className="font-mono text-accent">{state.ticker}</span>…
            </p>
            {/* Set expectations honestly: this is several sequential LLM calls,
                not a cache lookup. A bare spinner would read as "stuck". */}
            <p className="mt-1 text-xs text-neutral-600">
              Retrieval → bull / bear → fact-check → synthesis. This takes a
              while.
            </p>
          </div>
        )}

        {state.status === "error" && (
          <ErrorState error={state.error} ticker={state.ticker} />
        )}

        {state.status === "success" && (
          <>
            <div className="mb-4 flex items-baseline gap-3">
              <h2 className="font-mono text-lg text-accent">
                {state.note.ticker}
              </h2>
              <span className="text-xs text-neutral-600">
                research note · not investment advice
              </span>
            </div>
            <ResearchNoteView
              note={state.note}
              onSelectCitation={setActiveCitation}
              activeCitation={activeCitation}
            />
          </>
        )}
      </div>

      <SourcePanel citation={activeCitation} onClose={closePanel} />
    </main>
  );
}
