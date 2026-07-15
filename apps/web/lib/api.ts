/**
 * Typed API client for the CONSILIUM service.
 *
 * WHY this is a module and not inline `fetch` calls in components:
 * CLAUDE.md requires every external call to have explicit error handling and no
 * silent-failure path. Centralising the calls means each failure mode —
 * unreachable API, non-2xx, malformed body — is classified *once*, into a
 * discriminated `ApiError`, so the UI can say what actually broke instead of
 * rendering an empty state that looks like "no results".
 */
import { z } from "zod";
import {
  researchNoteSchema,
  sourceDocumentSchema,
  type Citation,
  type ResearchNote,
  type SourceDocument,
} from "./schemas";

/**
 * Base URL for the API as seen *from the browser*.
 *
 * WHY the localhost default: under docker-compose the browser runs on the host,
 * so it must reach the published port — not the compose service name `api`,
 * which only resolves inside the compose network. See apps/web/.env.example.
 */
const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ??
  "http://localhost:8000";

/**
 * Why a request failed, in terms the UI can act on.
 *
 * - `network`   — the API wasn't reachable at all (is the stack up?)
 * - `not_found` — 404: a real "this doesn't exist" answer, not an outage
 * - `http`      — the API answered, but with an error status
 * - `schema`    — the API answered 2xx with a body that isn't the agreed shape;
 *                 an API/UI contract drift, and the bug we most want surfaced
 */
export type ApiErrorKind = "network" | "not_found" | "http" | "schema";

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status?: number;
  /** Zod's issue list when `kind === "schema"` — the exact field that drifted. */
  readonly issues?: z.ZodIssue[];

  constructor(
    kind: ApiErrorKind,
    message: string,
    opts?: { status?: number; issues?: z.ZodIssue[] },
  ) {
    super(message);
    this.name = "ApiError";
    this.kind = kind;
    this.status = opts?.status;
    this.issues = opts?.issues;
  }
}

/** Pull FastAPI's `{"detail": ...}` out of an error body, best-effort. */
async function readDetail(resp: Response): Promise<string> {
  try {
    const body = await resp.json();
    const detail = (body as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (detail) return JSON.stringify(detail);
  } catch {
    // Non-JSON error body (e.g. a proxy's HTML 502). Fall through to status.
  }
  return `${resp.status} ${resp.statusText}`;
}

/**
 * GET + parse, with every failure mode mapped to an `ApiError`.
 *
 * The `signal` parameter lets callers abort a superseded request — see
 * `useResearch`, where a second ticker submitted mid-flight must not have its
 * result overwritten by the first one landing late.
 */
async function getJson<T>(
  path: string,
  // WHY `ZodType<T, ZodTypeDef, unknown>` and not the shorter `ZodType<T>`:
  // the latter is `ZodType<T, ZodTypeDef, T>` — it pins the schema's *input*
  // type to its output. Our schemas use `.default(null)`, which makes those
  // two differ (input allows the field to be absent, output never is), so the
  // short form fails to match. Declaring the input as `unknown` is also simply
  // the truth: what we hand it is an unvalidated `response.json()`.
  schema: z.ZodType<T, z.ZodTypeDef, unknown>,
  signal?: AbortSignal,
): Promise<T> {
  let resp: Response;
  try {
    resp = await fetch(`${API_BASE_URL}${path}`, {
      signal,
      headers: { Accept: "application/json" },
      // Research runs are live LLM calls; a cached note would be misleading.
      cache: "no-store",
    });
  } catch (err) {
    // Let aborts propagate untouched — they're control flow, not failures.
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new ApiError(
      "network",
      `Could not reach the API at ${API_BASE_URL}. Is the stack running (docker compose up)?`,
    );
  }

  if (resp.status === 404) {
    throw new ApiError("not_found", await readDetail(resp), { status: 404 });
  }
  if (!resp.ok) {
    throw new ApiError("http", await readDetail(resp), { status: resp.status });
  }

  let body: unknown;
  try {
    body = await resp.json();
  } catch {
    throw new ApiError("schema", "API returned a non-JSON body.");
  }

  const parsed = schema.safeParse(body);
  if (!parsed.success) {
    // Loud on purpose: a 2xx with the wrong shape means the API and this client
    // have drifted apart, which is exactly the class of bug the schema exists
    // to catch. Never coerce or partially render it.
    throw new ApiError(
      "schema",
      "API response did not match the expected schema (API/UI contract drift).",
      { issues: parsed.error.issues },
    );
  }
  return parsed.data;
}

/** Run the full agent graph for a ticker. GET /research/{ticker} */
export function fetchResearchNote(
  ticker: string,
  signal?: AbortSignal,
): Promise<ResearchNote> {
  return getJson(
    `/research/${encodeURIComponent(ticker.trim().toUpperCase())}`,
    researchNoteSchema,
    signal,
  );
}

/** Dereference one citation to its evidence. GET /sources/{type}/{id} */
export function fetchSource(
  citation: Pick<Citation, "source_type" | "source_id">,
  signal?: AbortSignal,
): Promise<SourceDocument> {
  return getJson(
    `/sources/${citation.source_type}/${citation.source_id}`,
    sourceDocumentSchema,
    signal,
  );
}
