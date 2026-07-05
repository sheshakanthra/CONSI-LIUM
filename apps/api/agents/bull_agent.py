"""bull_agent — the strongest evidence-backed *bullish* thesis (LLM-driven).

Charter (scoped system prompt below): argue the bull case for the ticker, but
ONLY from what retrieval can support. The agent gathers stance-specific evidence
from retrieval, then prompts **Claude** to construct the thesis and select/phrase
the supporting claims. Every claim is re-anchored to a real retrieval citation in
``reasoning.build_thesis`` — a claim that cites evidence we didn't supply is
dropped — so the Claim schema's "citations required" guarantee is preserved even
though the wording now comes from the LLM.
"""

from __future__ import annotations

from pydantic import BaseModel

from agents.deps import AgentDeps
from agents.reasoning import build_thesis
from agents.types import Claim, ClaimStance

SYSTEM_PROMPT = """\
You are the Bull Agent. Build the strongest BULLISH investment thesis for the
given company, citing only the evidence provided to you (each item is tagged with
an id like E1, E2). You may not introduce numbers, facts, or claims that the
provided evidence does not contain. Every claim must cite exactly one evidence id.
If the evidence is thin, say so rather than inventing support.
"""

# Probes chosen to surface positive/growth evidence. Kept explicit and auditable.
_BULL_PROBES: list[str] = [
    "What was revenue in Q1 FY27?",
    "What was EBITDA?",
    "What was net profit?",
    "What was EPS?",
    "How did revenue grow?",
    "What did the board recommend?",  # a dividend recommendation reads bullish
]


class BullThesis(BaseModel):
    """Bull agent output schema."""

    ticker: str
    thesis_summary: str
    claims: list[Claim]


class BullAgent:
    async def run(self, deps: AgentDeps, ticker: str) -> BullThesis:
        summary, claims = await build_thesis(
            deps, ticker, _BULL_PROBES, ClaimStance.BULL, SYSTEM_PROMPT
        )
        return BullThesis(ticker=ticker, thesis_summary=summary, claims=claims)
