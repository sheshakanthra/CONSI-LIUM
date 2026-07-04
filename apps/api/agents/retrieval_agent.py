"""retrieval_agent — Phase 2 retrieval exposed as a tool for other agents.

This is the one agent that touches the retrieval layer. Bull, bear, and the
fact-checker never query the database directly; they call this tool. Centralising
retrieval here means:
  * every claim in the system has a single, consistent provenance path, and
  * the fact-checker can issue its OWN independent calls through the same tool,
    with no privileged access to what bull/bear already retrieved.

Its "output schema" is the retrieval layer's ``Answer`` (already a validated
Pydantic contract with citations, confidence, and the insufficient-evidence
outcome), so there's nothing to re-wrap.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from retrieval.service import QAService
from retrieval.types import Answer

SYSTEM_PROMPT = """\
You are the Retrieval Agent. Given a question and a ticker, return the best
evidence from the indexed filings/tables with citations and a confidence, or
report insufficient evidence. You never speculate beyond retrieved sources.
"""


class RetrievalAgent:
    """Thin tool wrapper around the Phase 2 QA service."""

    def __init__(self, qa: QAService | None = None) -> None:
        self._qa = qa or QAService()

    async def retrieve(self, session: AsyncSession, ticker: str, question: str) -> Answer:
        """Answer one question for one ticker, with citations."""
        return await self._qa.answer_question(session, question, ticker)
