"use client";

/**
 * Research-request state machine.
 *
 * WHY a hook with an explicit status union rather than the usual
 * `loading`/`data`/`error` triple of booleans: those permit impossible states
 * (loading *and* error), and this request is slow enough — a full agent graph
 * run, several live LLM calls — that the UI genuinely has to be right about
 * which state it's in. One discriminated `status` makes the illegal
 * combinations unrepresentable.
 *
 * WHY the abort + request-id guard: a run takes many seconds, so a user can
 * easily submit a second ticker before the first returns. Without this, the
 * stale response can land last and render *the wrong ticker's note* under the
 * new ticker's heading — a silent correctness bug, and precisely the sort of
 * thing this project refuses to hand-wave.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, fetchResearchNote } from "./api";
import type { ResearchNote } from "./schemas";

export type ResearchState =
  | { status: "idle" }
  | { status: "loading"; ticker: string }
  | { status: "success"; ticker: string; note: ResearchNote }
  | { status: "error"; ticker: string; error: ApiError };

export function useResearch() {
  const [state, setState] = useState<ResearchState>({ status: "idle" });
  const inFlight = useRef<AbortController | null>(null);

  // Abort any live request when the component unmounts, so a late response
  // can't call setState on a dead component.
  useEffect(() => () => inFlight.current?.abort(), []);

  const run = useCallback(async (rawTicker: string) => {
    const ticker = rawTicker.trim().toUpperCase();
    if (!ticker) return;

    // Supersede the previous run. The abort makes the old promise reject with
    // AbortError, which we swallow below — only the newest request may write.
    inFlight.current?.abort();
    const controller = new AbortController();
    inFlight.current = controller;

    setState({ status: "loading", ticker });
    try {
      const note = await fetchResearchNote(ticker, controller.signal);
      if (controller.signal.aborted) return;
      setState({ status: "success", ticker, note });
    } catch (err) {
      if (controller.signal.aborted) return; // superseded — not a failure
      setState({
        status: "error",
        ticker,
        error:
          err instanceof ApiError
            ? err
            : // Anything not already classified is still reported, never
              // swallowed — an unknown failure is worse to hide than to show.
              new ApiError("network", (err as Error)?.message ?? "Unknown error"),
      });
    }
  }, []);

  return { state, run };
}
