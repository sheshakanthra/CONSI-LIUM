"""Agent dependencies.

WHY inject deps rather than let nodes reach for globals: the graph nodes stay
pure-ish functions of (state, deps), which makes them unit-testable and lets the
integration test build a graph against the same shared retrieval tool.

Each node opens its OWN session from ``session_factory``. That's deliberate:
bull/bear/quant run in the same LangGraph super-step (concurrently), and giving
each its own async session avoids sharing one connection across tasks.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import async_sessionmaker

from agents.retrieval_agent import RetrievalAgent
from app.db import SessionLocal


@dataclass
class AgentDeps:
    retrieval: RetrievalAgent
    session_factory: async_sessionmaker


def default_deps() -> AgentDeps:
    """Deps used by the running service (shared retrieval tool + app engine)."""
    return AgentDeps(retrieval=RetrievalAgent(), session_factory=SessionLocal)
