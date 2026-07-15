"""FastAPI application entrypoint.

WHY this file stays thin: per CLAUDE.md the agent/business logic lives in
dedicated modules. This is the composition root only — it wires config, logging,
the app instance, the health check, and mounts each layer's router.
"""

import logging
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.config import Settings, get_settings
from app.db import engine
from agents.api import router as research_router
from retrieval.api import router as qa_router
from retrieval.sources_api import router as sources_router

settings = get_settings()


def configure_logging(cfg: Settings) -> None:
    """Attach a stdout handler to the app's logger namespace.

    WHY this is needed: uvicorn configures its own ("uvicorn.*") loggers but
    leaves the root logger at WARNING with no handler, so our
    ``logging.getLogger("consilium.*")`` INFO records — including the per-call
    ``[llm]`` cost/token line — are silently dropped. We configure the
    "consilium" parent logger directly (own handler, INFO level, no propagation
    to root) so app logs reliably reach stdout → ``docker compose logs api``,
    independent of whatever uvicorn does to the root logger. Idempotent.
    """
    level = getattr(logging, cfg.log_level.upper(), logging.INFO)
    app_logger = logging.getLogger("consilium")
    app_logger.setLevel(level)
    app_logger.propagate = False  # our own handler emits; don't double via root
    if not any(isinstance(h, logging.StreamHandler) for h in app_logger.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
        app_logger.addHandler(handler)


configure_logging(settings)
logging.getLogger("consilium.api").info(
    "CONSILIUM API starting (env=%s, log_level=%s, llm_provider=%s, model=%s)",
    settings.environment,
    settings.log_level,
    settings.llm_provider,
    settings.groq_model if settings.llm_provider == "groq" else settings.agent_model,
)

app = FastAPI(
    title=settings.app_name,
    version="0.3.0",
    description="CONSILIUM API — ingestion + retrieval/QA + multi-agent research.",
)

# CORS. The dashboard is served from a different origin (:3000) than this API
# (:8000), so the browser preflights and blocks cross-origin fetches without
# these headers. Registered BEFORE the routers so it wraps every route,
# including the OPTIONS preflight CORSMiddleware answers on their behalf.
#
# WHY the allowlist is explicit and not "*": the API is read-only today, but
# `allow_origins=["*"]` is the kind of default that quietly outlives the
# prototype. The origins come from config so production narrows them via env
# (CORS_ALLOWED_ORIGINS) rather than a code change.
#
# WHY allow_credentials is False: the API has no cookie/session auth, so
# credentialed requests are meaningless here — and enabling it would forbid the
# "*" wildcard anyway. Revisit if auth lands.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=False,
    # The dashboard only reads. Listing the verbs beats "*" so an unintended
    # write endpoint isn't reachable from a browser the day it's added.
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Accept"],
)

logging.getLogger("consilium.api").info(
    "CORS allowed origins: %s", settings.cors_origins_list
)

# Retrieval/QA endpoints (POST /qa).
app.include_router(qa_router)
# Citation resolution (GET /sources/{source_type}/{source_id}) — backs the
# dashboard's drill-down from a claim's citation to the source page/cell.
app.include_router(sources_router)
# Multi-agent research endpoint (GET /research/{ticker}).
app.include_router(research_router)


@app.get("/health", tags=["ops"])
async def health() -> dict[str, str]:
    """Liveness + DB-readiness probe.

    WHY check the DB here: "no silent failure" (CLAUDE.md) — a health check
    that only returns 200 for the web process hides the most common outage
    (Postgres unreachable). We issue a trivial `SELECT 1`; if the connection
    fails the exception surfaces as a 500 and the report field reads "error".
    """
    db_status = "ok"
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 — we want to report, not swallow.
        db_status = f"error: {exc.__class__.__name__}"

    return {
        "status": "ok",
        "service": settings.app_name,
        "environment": settings.environment,
        "database": db_status,
    }
