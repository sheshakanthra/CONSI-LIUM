# Phase 6 — The Research Dashboard

> Design note for the frontend phase. Per CLAUDE.md, each phase ships a short
> note capturing the design decisions — this is the resume/interview artifact.

> **Not investment advice.** The dashboard renders a pipeline's output over
> *synthetic* sample filings and a synthetic price series. It demonstrates
> traceability, not market performance.

## What this phase delivers

| Piece | Path | What it proves |
|-------|------|----------------|
| Citation resolver | `apps/api/retrieval/sources.py` | a citation dereferences to real evidence |
| `/sources` endpoint | `apps/api/retrieval/sources_api.py` | drill-down has an API to call |
| Zod schema mirrors | `apps/web/lib/schemas.ts` | the schema contract survives the process boundary |
| Typed API client | `apps/web/lib/api.ts` | every failure mode is classified, none silent |
| Request state machine | `apps/web/lib/useResearch.ts` | slow, abortable runs can't render stale results |
| Research view | `apps/web/components/` | fact-check verdicts are structural, not cosmetic |
| CORS middleware | `apps/api/app/main.py` + `config.py` | the browser can actually call the API |
| Round-trip tests | `apps/api/tests/test_sources.py` | no dangling citations |
| CORS tests | `apps/api/tests/test_cors.py` | the transport works, not just the payload |

## The gap this phase actually closed

Phases 1–5 built a pipeline that emits `Citation` objects: `{source_type,
source_id, page_number, ...}`. That is a **pointer** — deliberately, so evidence
text isn't copied (and possibly mutated) as it flows between agent nodes.

But the project's headline claim is *"every claim traces back to a source PDF
page, table cell, or transcript timestamp."* Before this phase, that claim was
true **internally** and unverifiable **externally**: `chunk 412` proves nothing
to a reader. There was no way — API or UI — to turn a pointer back into the
thing it points at.

So Phase 6 is not "add a frontend to the existing API". The dashboard needed a
backend capability that didn't exist, and roughly a third of the work is
`GET /sources/{source_type}/{source_id}`. **The UI is what makes the traceability
claim falsifiable**, and that's the honest framing of the phase.

## Design decisions

### 1. Citations resolve on demand, not inline in the note

The research note carries pointers; the evidence panel fetches by id when the
reader clicks.

- A note can cite the same chunk from many claims — inlining duplicates it.
- The evidence shown is read **from the DB at view time**, not a copy that
  travelled through the agent graph. If they ever disagreed, the panel shows the
  source of truth.
- The research payload stays small.

### 2. Zod parse at the boundary, not a TypeScript cast

CLAUDE.md: *"every agent output is validated against a Pydantic schema before
being passed to the next node — no raw string handoffs."* That rule doesn't stop
at the process boundary. **The browser is the last node in the graph.**

`await resp.json() as ResearchNote` is a lie the compiler can't catch: TS types
evaporate at runtime, so a drifted API silently renders `undefined` into the DOM
— exactly the silent failure the Python side is engineered to prevent. Every
response is parsed; a 2xx with the wrong shape raises `ApiError{kind:"schema"}`
carrying Zod's field paths, and the UI renders it as "API/UI contract drift"
with the offending fields listed.

### 3. Four error kinds, four messages

`network | not_found | http | schema`. "No silent failure" is about
*actionability*, and these have four different fixes — start the stack, check the
ticker, read `docker compose logs api`, update the Zod mirror. Collapsing them
into "Something went wrong" would throw away a diagnosis the client already made.

The `not_found` / empty-note case says **"No claims survived fact-checking"**,
not "no results" — those are different findings, and the difference is the point
of the product.

### 4. Verdict labels are structural

The synthesizer guarantees that a claim's status is a property of the graph:
SUPPORTED claims are the thesis; CONTRADICTED/UNVERIFIABLE ones are surfaced as
disputed, never quietly presented as fact. A UI that hid the disputed section,
dropped the badge, or filtered out claims with no evidence would break that
guarantee **at the last mile — the one place it matters, in front of the
reader**. So: badges always render, the disputed section always renders when
non-empty, and a claim with zero citations renders with an explicit
"no independent evidence found" marker rather than being hidden.

### 5. Abort + supersede on the request

A research run is many sequential LLM calls. A user can easily submit a second
ticker before the first returns. Without a guard, the stale response can land
last and render **the wrong ticker's note under the new ticker's heading** — a
silent correctness bug. `useResearch` aborts the previous controller and drops
any response whose controller is already aborted.

### 6. No charting library

The quant sparkline is hand-rolled inline SVG. Recharts/Chart.js would add a
sizeable client bundle to draw one unlabelled polyline of ~5 points —
unjustified weight, the same reasoning that kept numpy out of the quant agent
(`docs/phase4-quant.md`). Deliberately axis-less: the series is a short synthetic
projection, and axes would imply a precision it doesn't have. The numbers live in
the text beside it.

Only one dependency was added this phase: **zod** — already named in CLAUDE.md's
stack.

## Bugs found and fixed along the way

- **`z.ZodType<T>` rejected schemas using `.default()`.** The short form is
  `ZodType<T, ZodTypeDef, T>` — it pins a schema's *input* type to its output,
  but `.default(null)` makes them differ. Declaring the client's parameter as
  `ZodType<T, ZodTypeDef, unknown>` is both the fix and the truth: what it parses
  *is* an unvalidated `response.json()`.
- **The Next build escaped the repo.** With `output: "standalone"`, Next infers
  the workspace root by walking up for a lockfile — and found a stray
  `package-lock.json` in the developer's *home directory*, laying the traced
  bundle out relative to that. Pinned `outputFileTracingRoot` to the app, so the
  build depends on the repo alone rather than on whatever sits above the
  checkout.
- **`TestClient` can't test a DB-backed endpoint in this suite.** The first cut
  of `test_sources.py` failed with *"got Future attached to a different loop"*.
  Starlette's `TestClient` drives the app from a worker thread on its **own**
  event loop, while `app.db.engine`'s asyncpg pool is bound to the session-scoped
  loop (the constraint pytest.ini already documents). Switched the DB-backed
  tests to `httpx.AsyncClient` + `ASGITransport`, which awaits the app in the
  current loop; `TestClient` stays only for the two no-DB validation tests. A
  neat illustration that the async-boundary rules apply to the *tests*, not just
  the app.

## Known limitations

- **`packages/shared-types` is still empty.** The Zod schemas live in
  `apps/web/lib/schemas.ts` and parity is hand-maintained. The web Docker build
  context is `./apps/web`, so a shared package is literally un-`COPY`-able
  without moving the context to the repo root and reworking a Dockerfile full of
  hard-won pnpm/sharp workarounds — a deployment-topology change that had no
  business riding along with a feature. Full reasoning and the intended fix
  (generate Zod from FastAPI's `/openapi.json`, diff it in CI) are in
  `packages/shared-types/README.md`.
- **No frontend test runner.** The API side of this phase is covered by
  `tests/test_sources.py` (including "every citation a QA answer emits must
  resolve"), which is what satisfies CLAUDE.md's per-phase test bar. Adding
  Vitest + Testing Library to `apps/web` is a stack addition, and CLAUDE.md says
  to surface those rather than slip them in — so the component tests are
  proposed, not assumed.
- **Ticker entry is unvalidated free text.** An unknown ticker is a legitimate
  empty note, so it's handled as a finding, not an error. There's no ticker
  autocomplete because there's no ticker registry — only whatever has been
  ingested.
- **No trace viewer.** README advertises "dashboard + trace viewer". This phase
  is the dashboard; per-node latency/token/retry traces depend on the tracing
  decision CLAUDE.md flags as needing a call (LangSmith vs. a self-rolled JSON
  logger). That's Phase 7.

## "Done" checklist (CLAUDE.md)

- [x] Runs end-to-end locally via docker-compose (db + api + web).
- [x] Tests: `apps/api/tests/test_sources.py` — unit (input validation) +
      integration (citation round-trip, dangling-pointer sweep);
      `apps/api/tests/test_cors.py` — cross-origin headers + env parsing.
      **38 passing.**
- [x] This design note.

### What was actually verified (not just asserted)

Against the running stack, on the `ACME` synthetic filing:

- `docker compose up` — db healthy, api healthy, web serving `/dashboard` (200).
- Full API suite: **31 passed**, including the 6 new `test_sources.py` cases.
- `/sources` live: chunk → text + provenance; table → header/rows grid intact;
  unknown id → 404; bad kind → 422.
- `GET /research/ACME` → a real note (6 supported / 1 disputed claims, live
  bearish quant signal at 0.504 confidence).
- **That live payload parsed cleanly against the Zod mirrors**, as did both
  `/sources` shapes — so the hand-maintained Pydantic↔Zod parity holds *today*.
- **All 8 citations on the note resolved** through the same endpoint the
  evidence panel calls. Zero dangling pointers.
- **Driven in real headless Chrome over CDP:** typed `ACME`, clicked *Run
  research*, the note rendered with 8 citation chips; clicking the first chip
  opened the evidence panel and resolved `table · id 1 · page 1` to the actual
  grid (Revenue 1,245 / 1,090 / 14.2). No console errors beyond a
  `favicon.ico` 404 (`apps/web/public/` is empty — cosmetic, pre-existing).

### The CORS bug, and why the first pass missed it

The above browser run only happened *after* a real bug: the dashboard couldn't
call the API at all. **`Access-Control-Allow-Origin` was missing** — the API and
the web app are different origins (`:8000` vs `:3000`), so the browser blocked
every fetch.

The uncomfortable part is *how it was found*: in a browser console, by a human —
not by 31 passing tests, and not by the verification pass that checked every
contract with curl and Node. **No server-to-server client enforces the
same-origin policy.** curl, httpx, and pytest will all happily fetch an API that
is completely unusable from the UI it exists to serve. A green suite proved
nothing about the one caller that mattered.

Fixed with `CORSMiddleware` driven by `CORS_ALLOWED_ORIGINS` (see below), and
covered by `tests/test_cors.py` — which asserts on response *headers*, the only
thing a browser actually gates on. The lesson generalises: **for a browser
client, "the endpoint returns correct JSON" and "the app works" are independent
claims.** Verify the transport, not just the payload.

## CORS configuration

`CORS_ALLOWED_ORIGINS` — comma-separated origins, defaulting to
`http://localhost:3000`. Production narrows it via env, no code change
(CLAUDE.md: config via .env, never hardcoded).

Decisions worth noting:

- **Comma-separated `str`, not `list[str]`.** pydantic-settings JSON-decodes
  complex types from the environment, so a `list[str]` field would require
  `CORS_ALLOWED_ORIGINS=["http://localhost:3000"]` in `.env` and raise a
  `SettingsError` on the obvious plain value. A `str` + a parsed
  `cors_origins_list` property keeps the env var human-writable.
- **An explicit allowlist, never `*`.** `allow_origins=["*"]` is the kind of
  default that quietly outlives the prototype. `tests/test_cors.py` includes a
  negative case (a disallowed origin gets **no** header) specifically so a
  regression to `*` fails the suite — without it, every other CORS test would
  still pass while the allowlist did nothing.
- **`allow_credentials=False`.** There's no cookie/session auth, so credentialed
  requests are meaningless here. Revisit if auth lands.
- **Deliberately NOT set in docker-compose's `environment:` block.** That block
  overrides `env_file` — the exact precedence bug fixed in Phase 5. The code
  default already covers compose dev, so a user's own `.env` value wins.
