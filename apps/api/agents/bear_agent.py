"""bear_agent — the strongest evidence-backed *bearish* thesis (LLM-driven).

Symmetric to the bull agent: same sourcing guarantee, opposite stance. Its probes
hunt for declines, risks, and caveats; Claude then constructs the bearish thesis
from that evidence, and every claim is re-anchored to a real retrieval citation
(unsourced claims dropped) in ``reasoning.build_thesis``. On a deliberately rosy
sample filing the bear case may be thin — that's honest, and the agent says so
rather than manufacturing negatives.
"""

from __future__ import annotations

from pydantic import BaseModel

from agents.deps import AgentDeps
from agents.reasoning import build_thesis
from agents.types import Claim, ClaimStance

SYSTEM_PROMPT = """\
You are the Bear Agent. Build the strongest BEARISH investment thesis for the
given company, citing only the evidence provided to you (each item is tagged with
an id like E1, E2). Surface declines, risks, and data-quality caveats. You may not
invent weaknesses the evidence does not contain; every claim must cite exactly one
evidence id. If the evidence is thin, say so.
"""

# Probes chosen to surface declines / risks / caveats.
_BEAR_PROBES: list[str] = [
    "What segment declined or dropped?",
    "What are the risks or limitations of this document?",
    "Is this a real filing?",
    "What was the decline in margin?",
    "What was Q1 FY26 revenue?",  # prior-period base for a slowdown argument
]


class BearThesis(BaseModel):
    """Bear agent output schema."""

    ticker: str
    thesis_summary: str
    claims: list[Claim]


class BearAgent:
    async def run(self, deps: AgentDeps, ticker: str) -> BearThesis:
        summary, claims = await build_thesis(
            deps, ticker, _BEAR_PROBES, ClaimStance.BEAR, SYSTEM_PROMPT
        )
        return BearThesis(ticker=ticker, thesis_summary=summary, claims=claims)
