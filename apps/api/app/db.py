"""Async SQLAlchemy engine and session factory.

WHY async SQLAlchemy 2.0: CLAUDE.md locks the ORM to SQLAlchemy 2.0 (async)
with explicit schemas and no hidden-SQL magic. FastAPI is async end-to-end, so
a blocking driver would tie up the event loop under load. We expose a session
dependency rather than a global session so each request gets its own unit of
work with a clean transaction boundary.
"""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings

# Created at import time so the connection pool is shared process-wide. The
# asyncpg driver is implied by the URL scheme (postgresql+asyncpg://).
engine: AsyncEngine = create_async_engine(
    get_settings().database_url,
    echo=False,
    pool_pre_ping=True,  # WHY: transparently recycle connections dropped by
    # Postgres so the first request after an idle period doesn't fail.
)

# expire_on_commit=False keeps ORM objects usable after commit, which matters
# when returning them from a request handler after the session closes.
SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a scoped async session.

    WHY a generator dependency: it guarantees the session is closed (and the
    connection returned to the pool) even if the request handler raises.
    """
    async with SessionLocal() as session:
        yield session
