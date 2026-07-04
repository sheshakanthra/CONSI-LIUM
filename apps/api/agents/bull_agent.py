"""bull_agent — the strongest evidence-backed *bullish* thesis.

Charter (scoped system prompt below): argue the bull case for the ticker, but
ONLY from what retrieval can support. It asks a fixed set of "what's going well?"
probes; each sourced answer becomes a citation-carrying claim. The thesis summary
is assembled from those claims, so the agent literally cannot introduce a claim
that retrieval didn't back.

LLM seam: replace ``_summarise`` (and, later, the probe selection) with a
ReasonerLLM call using SYSTEM_PROMPT + the retrieved claims to produce fluent
argumentation. The claim set — and thus the sourcing guarantee — stays intact.
"""

from __future__ import annotations

from pydantic import BaseModel

from agents.claims import gather_claims
from agents.deps import AgentDeps
from agents.types import Claim, ClaimStance

SYSTEM_PROMPT = """\
You are the Bull Agent. Build the strongest BULLISH investment thesis for the
given company, citing only evidence returned by the Retrieval Agent. You may not
introduce numbers, facts, or claims that retrieval did not return. If evidence is
thin, say so rather than inventing support.
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


def _summarise(ticker: str, claims: list[Claim]) -> str:
    if not claims:
        return f"No retrieval-supported bullish evidence was found for {ticker}."
    return (
        f"Bull case for {ticker} rests on {len(claims)} sourced point(s): "
        + "; ".join(c.text.rstrip(".") for c in claims)
        + "."
    )


class BullAgent:
    async def run(self, deps: AgentDeps, ticker: str) -> BullThesis:
        async with deps.session_factory() as session:
            claims = await gather_claims(
                deps, session, ticker, _BULL_PROBES, ClaimStance.BULL
            )
        return BullThesis(
            ticker=ticker, thesis_summary=_summarise(ticker, claims), claims=claims
        )
