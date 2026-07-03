# Phase 01 — Monorepo Scaffold

> Design note for the scaffold phase. Per CLAUDE.md, each phase ships a short
> markdown note capturing the design decision (resume/interview talking points).

## What this phase delivers

A runnable three-service skeleton — nothing more, no business logic:

- **`apps/api`** — FastAPI app with a single `/health` endpoint, typed config
  via `pydantic-settings`, and an async SQLAlchemy 2.0 engine pointed at
  `DATABASE_URL`.
- **`apps/web`** — Next.js 15 (App Router) + Tailwind, with a placeholder
  `/dashboard` page. `/` redirects to it.
- **`db`** — Postgres 16 via the `pgvector/pgvector:pg16` image, with the
  `vector` extension enabled at bootstrap.

## Decisions worth defending

1. **Health check probes the database, not just the process.** A 200 that
   ignores DB reachability hides the most common outage. The endpoint runs
   `SELECT 1` and reports `database: ok | error:<Type>`, honouring the
   "no silent failure" rule.
2. **`pgvector` enabled via an init SQL script, not app migrations.**
   `CREATE EXTENSION` needs superuser; keeping it at cluster bootstrap lets the
   application role stay least-privileged.
3. **API waits on a real DB healthcheck** (`pg_isready`) via compose
   `depends_on: condition: service_healthy`, so the API never boots against a
   half-initialised Postgres.
4. **Single `DATABASE_URL`** instead of discrete host/port fields — one value
   consumed identically by compose, prod, and async SQLAlchemy; no drift.

## "Done" checklist (CLAUDE.md)

- [x] Runs end-to-end locally via `docker-compose up`.
- [x] Has a test (`apps/api/tests/test_health.py`).
- [x] Has this design note.
