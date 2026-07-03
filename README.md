# CONSILIUM

A multi-agent research-and-analysis platform built on a LangGraph agent graph,
retrieval over `pgvector`, and a fact-checking pipeline as its core
differentiator. Solo-built portfolio project by **Sheshakanth**.

> **Status:** Phase 01 — scaffold only. No business logic yet. See
> [`docs/01-scaffold.md`](docs/01-scaffold.md).

## Architecture

```
                          ┌──────────────────────────┐
   Browser ──────────────▶│  apps/web  (Next.js 15)   │
                          │  App Router + Tailwind     │
                          └────────────┬──────────────┘
                                       │  HTTP (NEXT_PUBLIC_API_BASE_URL)
                                       ▼
                          ┌──────────────────────────┐
                          │  apps/api  (FastAPI)      │
                          │  LangGraph agent graph *   │
                          │  async SQLAlchemy 2.0      │
                          └────────────┬──────────────┘
                                       │  asyncpg (DATABASE_URL)
                                       ▼
                          ┌──────────────────────────┐
                          │  db (Postgres 16)          │
                          │  + pgvector extension      │
                          └──────────────────────────┘

   * agent graph, retrievers, ASR, and the fact-checking node arrive in
     later phases — see the roadmap in CLAUDE.md.
```

> _Architecture diagram placeholder — replace with a rendered diagram
> (e.g. Excalidraw / Mermaid export) as the agent graph solidifies._

## Repository layout

```
consilium/
  apps/
    api/            # FastAPI service (health check, config, async DB engine)
    web/            # Next.js 15 dashboard
  packages/
    shared-types/   # Zod/Pydantic schema-parity definitions (later)
  eval/
    golden_set/     # golden-set fixtures (later)
    scripts/        # RAGAS + custom harness (later)
  data/             # gitignored — raw filings & transcripts
  infra/
    postgres/init/  # pgvector bootstrap SQL
  docs/             # per-phase design notes
  docker-compose.yml
```

## Prerequisites

- Docker + Docker Compose
- (For running services outside Docker) Python 3.11 and Node 20 + pnpm

## Setup — run the full stack

```bash
# 1. Create env files from the templates (do NOT commit the real ones).
cp apps/api/.env.example apps/api/.env
cp apps/web/.env.example apps/web/.env.local

# 2. Bring everything up (Postgres + pgvector, API, web).
docker compose up --build

# 3. Verify the API health check (reports DB reachability too).
curl http://localhost:8000/health
# => {"status":"ok","service":"consilium-api",...,"database":"ok"}

# Web dashboard:  http://localhost:3000  (/ redirects to /dashboard)
```

## Local development (without Docker)

**API**

```bash
cd apps/api
python -m venv .venv && source .venv/Scripts/activate   # Git Bash on Windows
pip install -r requirements.txt
# Point DATABASE_URL at localhost (see .env.example) then:
uvicorn app.main:app --reload
pytest            # runs the health-check test
```

**Web**

```bash
cd apps/web
pnpm install
pnpm dev          # http://localhost:3000
```

> On Windows, run pnpm scripts via **Git Bash**, not PowerShell (CLAUDE.md).

## Conventions

Project rules — tech-stack locks, git discipline, agent/schema conventions, and
the phase definition of "done" — live in [`CLAUDE.md`](CLAUDE.md).
