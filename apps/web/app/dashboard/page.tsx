// Placeholder dashboard. No business logic yet (scaffold phase per CLAUDE.md).
// This exists only to prove the App Router + Tailwind pipeline renders.

export default function DashboardPage() {
  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col justify-center gap-4 px-6">
      <span className="text-sm font-medium uppercase tracking-widest text-neutral-500">
        CONSILIUM
      </span>
      <h1 className="text-3xl font-semibold tracking-tight">Dashboard</h1>
      <p className="text-neutral-400">
        Scaffold placeholder. Agent orchestration, filings analysis, and the
        fact-checking pipeline land in later phases.
      </p>
      <div className="mt-4 rounded-lg border border-neutral-800 bg-neutral-900/50 p-4 text-sm text-neutral-400">
        API health check:{" "}
        <code className="text-neutral-200">GET /health</code> on the API service
        (default <code className="text-neutral-200">http://localhost:8000</code>).
      </div>
    </main>
  );
}
