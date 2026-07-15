# shared-types

Zod ↔ Pydantic schema-parity definitions shared between `apps/web` and
`apps/api` (CLAUDE.md: "Zod/Pydantic schema parity definitions").

## Status: still empty — and here's why

Phase 6 defined the first real cross-language schemas (`ResearchNote`,
`NoteClaim`, `Citation`, `QuantSignal`, `SourceDocument`). They **did not land
here**. They live in [`apps/web/lib/schemas.ts`](../../apps/web/lib/schemas.ts).

That's a deliberate deferral, not an oversight:

1. **There is no pnpm workspace yet.** `apps/web` is a standalone package; there
   is no root `pnpm-workspace.yaml`. Importing from `packages/*` needs one.
2. **The web Docker build context is `./apps/web`.** A file under
   `packages/shared-types` is *outside* that context and cannot be `COPY`'d.
   Sharing the package means moving the context to the repo root and reworking
   the Dockerfile — whose pnpm/sharp workarounds were hard-won (see the comments
   in `apps/web/Dockerfile`).
3. **One consumer doesn't justify it.** These schemas have exactly one consumer
   today. Restructuring the build to share code with nobody is premature.

Doing (1) and (2) to satisfy a directory layout — while also shipping Phase 6 —
would have meant changing the deployment topology and the feature in one step.
Kept apart on purpose.

## What holds the contract instead, for now

Parity is maintained **by hand**, and every Zod schema names the Python model it
mirrors in a comment. Drift is caught **at runtime, at the boundary**: the API
client parses each response, and a 2xx body that doesn't match surfaces as a
loud `ApiError` of kind `schema` — carrying the exact field path — rather than
rendering `undefined` into the page. See `apps/web/lib/api.ts`.

That is weaker than compile-time parity. Stated plainly rather than papered over.

## The intended fix

Generate the Zod schemas from the API's OpenAPI document (FastAPI already
publishes one at `/openapi.json`, derived from the very same Pydantic models),
and fail CI on a diff against the committed output. That turns drift into a
**build** error and deletes the hand-maintenance problem instead of relocating
it.

Prerequisites: a root pnpm workspace, and the web build context moved to the
repo root.
