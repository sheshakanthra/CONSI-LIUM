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
from typing import Protocol

from sqlalchemy.ext.asyncio import async_sessionmaker

from agents.retrieval_agent import RetrievalAgent
from app.db import SessionLocal


class LLM(Protocol):
    """The reasoning seam: return a validated schema instance + usage.

    The real implementation is ``agents.llm_client.LLMClient`` (calls Claude);
    tests inject a deterministic fake with the same signature.
    """

    async def structured(self, *, system: str, user: str, schema, agent: str): ...


@dataclass
class AgentDeps:
    retrieval: RetrievalAgent
    session_factory: async_sessionmaker
    llm: LLM


def default_deps() -> AgentDeps:
    """Deps used by the running service (shared retrieval tool + app engine + LLM)."""
    from agents.llm_client import LLMClient

    return AgentDeps(
        retrieval=RetrievalAgent(), session_factory=SessionLocal, llm=LLMClient()
    )
