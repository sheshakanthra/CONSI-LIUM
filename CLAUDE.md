# CLAUDE.md — AlphaDesk Project Rules

## Identity
This is a solo-built portfolio project by Sheshakanth. All commits, authorship,
and public-facing attribution belong to Sheshakanth alone.

## Git rules (STRICT — do not violate)
- Claude Code NEVER runs git commands (no git add, commit, push, pull).
- Do not add Claude/AI co-author trailers to any commit message anywhere,
  even in drafted commit message suggestions.
- Sheshakanth commits manually, one logical change per commit, simple
  per-file message format.
- Sheshakanth runs `git pull origin main` before every push himself.
- On Windows, pnpm scripts are run via Git Bash, not PowerShell, to avoid
  shell incompatibilities. Do not generate PowerShell-only syntax in scripts.

## Tech stack (locked — do not substitute without asking)
- Backend: Python 3.11, FastAPI, Pydantic v2
- Orchestration: LangGraph (agent graph), LangChain (only for utility
  wrappers — retrievers, loaders — not for the agent logic itself)
- Vector store: pgvector on Postgres 16
- ORM: SQLAlchemy 2.0 (async) or Drizzle-equivalent discipline — explicit
  schemas, no ORM magic that hides SQL
- ASR: faster-whisper (local) for dev, Whisper API swap-in for prod option
- Frontend: Next.js 15 (App Router), TypeScript, Tailwind
- Eval: RAGAS + a custom golden-set harness (see Part C)
- Tracing: LangSmith (or a self-rolled JSON trace logger if LangSmith
  quota is a concern — ask before deciding)
- Containerization: Docker, docker-compose for local dev (Postgres+pgvector,
  API, frontend)
- Package management: pnpm for the frontend/monorepo tooling, pip + venv
  (or uv if available) for the Python service

## Monorepo structure
alphadesk/
  apps/
    api/            # FastAPI service
    web/             # Next.js dashboard
  packages/
    shared-types/    # Zod/Pydantic schema parity definitions
  eval/
    golden_set/
    scripts/
  data/
    filings/         # gitignored — raw PDFs
    transcripts/      # gitignored — raw audio + transcripts
  docker-compose.yml
  CLAUDE.md
  README.md

## Coding conventions
- Every agent node in LangGraph gets its own file under apps/api/agents/
- Every agent output is validated against a Pydantic schema before being
  passed to the next node — no raw string handoffs between agents
- No silent failure: every external API call (ASR, LLM, data provider) has
  explicit error handling and a fallback/log path
- Config via .env + pydantic-settings, never hardcoded keys
- Write docstrings that explain WHY a design choice was made, not just
  what the function does — this is a portfolio project, code should read
  like a teaching artifact

## What "done" means for each phase
A phase is not complete until:
1. It runs end-to-end locally via docker-compose
2. It has at least one test (unit or integration)
3. It has a short markdown note in /docs/ explaining the design decision
   for that phase (this becomes your resume/interview talking points)

## Do NOT
- Do not silently swap a library or model choice — surface it as a
  question first
- Do not write agent prompts as one giant mega-prompt — keep each agent's
  system prompt scoped to its single responsibility
- Do not skip the fact-checking agent step even under time pressure —
  it's the core differentiator of this project