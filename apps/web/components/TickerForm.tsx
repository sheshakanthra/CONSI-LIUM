"use client";

/**
 * Ticker entry.
 *
 * WHY the input is uppercased on change rather than only on submit: the API
 * scopes retrieval by an uppercase ticker (`research(ticker.upper())`), so
 * showing the user the exact string that will be queried avoids the small
 * confusion of typing `acme` and seeing a note headed `ACME`.
 *
 * WHY the submit button disables while loading: a research run is a live agent
 * graph execution costing real LLM tokens. The hook can safely supersede an
 * in-flight run, but silently burning tokens on double-submits is still waste
 * worth preventing at the UI.
 */
import { useState, type FormEvent } from "react";

type TickerFormProps = {
  onSubmit: (ticker: string) => void;
  isLoading: boolean;
};

export function TickerForm({ onSubmit, isLoading }: TickerFormProps) {
  const [value, setValue] = useState("");

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    onSubmit(value);
  }

  return (
    <form onSubmit={handleSubmit} className="flex gap-2">
      <label htmlFor="ticker" className="sr-only">
        Ticker symbol
      </label>
      <input
        id="ticker"
        name="ticker"
        value={value}
        onChange={(e) => setValue(e.target.value.toUpperCase())}
        placeholder="ACME"
        autoComplete="off"
        spellCheck={false}
        className="w-40 rounded border border-neutral-800 bg-neutral-950 px-3 py-2 font-mono text-sm text-neutral-100 outline-none transition-colors placeholder:text-neutral-700 focus:border-accent/60"
      />
      <button
        type="submit"
        disabled={isLoading || !value.trim()}
        className="rounded border border-accent/40 bg-accent/10 px-4 py-2 text-sm font-medium text-accent transition-colors hover:bg-accent/20 disabled:cursor-not-allowed disabled:border-neutral-800 disabled:bg-transparent disabled:text-neutral-700"
      >
        {isLoading ? "Deliberating…" : "Run research"}
      </button>
    </form>
  );
}
