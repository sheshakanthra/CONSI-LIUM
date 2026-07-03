"""FastAPI application entrypoint.

WHY this file stays thin: per CLAUDE.md the agent/business logic lives in
dedicated modules (agents/ etc.). This is the composition root only — it wires
config, the app instance, and a health check. No business logic yet.
"""

from fastapi import FastAPI
from sqlalchemy import text

from app.config import get_settings
from app.db import engine

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="CONSILIUM API — scaffold. No business logic yet.",
)


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
