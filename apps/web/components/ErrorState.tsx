/**
 * Failure rendering, one branch per `ApiError.kind`.
 *
 * WHY each kind gets its own copy instead of a single "Something went wrong":
 * CLAUDE.md's "no silent failure" rule is about *actionability*. These four
 * failures have four different fixes — start the stack, check the ticker, read
 * the API log, fix a schema drift — and collapsing them into one message throws
 * away the diagnosis the client already made.
 *
 * The `schema` branch prints Zod's issue paths because that error means the API
 * and this UI have genuinely diverged; the field path is the whole debugging
 * lead, and hiding it behind a console.log would waste it.
 */
import type { ApiError } from "@/lib/api";

export function ErrorState({ error, ticker }: { error: ApiError; ticker: string }) {
  const heading: Record<ApiError["kind"], string> = {
    network: "Cannot reach the API",
    not_found: `Nothing found for ${ticker}`,
    http: "The API returned an error",
    schema: "API / UI contract drift",
  };

  const hint: Record<ApiError["kind"], string> = {
    network:
      "The research service isn't responding. Start the stack with `docker compose up` and try again.",
    not_found:
      "Check the ticker, and confirm its filings have been ingested and indexed (`python -m retrieval.index`).",
    http: "The request reached the API but it failed. Check `docker compose logs api` for the traceback.",
    schema:
      "The API responded successfully but with an unexpected shape. The response schema changed without the UI's Zod mirror being updated — see apps/web/lib/schemas.ts.",
  };

  return (
    <section
      role="alert"
      className="rounded-lg border border-rose-500/40 bg-rose-500/5 p-5"
    >
      <h2 className="text-sm font-medium text-rose-400">{heading[error.kind]}</h2>
      <p className="mt-2 text-sm leading-relaxed text-neutral-400">
        {hint[error.kind]}
      </p>
      <p className="mt-3 font-mono text-xs text-neutral-600">{error.message}</p>

      {error.issues && error.issues.length > 0 && (
        <ul className="mt-3 space-y-1 border-t border-rose-500/20 pt-3">
          {error.issues.map((issue, i) => (
            <li key={i} className="font-mono text-xs text-neutral-500">
              {issue.path.join(".") || "(root)"}: {issue.message}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
