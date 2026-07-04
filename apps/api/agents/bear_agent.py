"""bear_agent — the strongest evidence-backed *bearish* thesis.

Symmetric to the bull agent: same sourcing guarantee, opposite stance. Its probes
hunt for declines, risks, and caveats. On a deliberately rosy sample filing the
bear case may be thin — that's honest, and the agent says so rather than
manufacturing negatives. (The synthetic filings do carry an explicit "this is not
a real filing" caveat, which is a legitimate data-quality risk the bear surfaces.)

LLM seam: identical to bull — swap ``_summarise``/probe selection for a
ReasonerLLM later; the retrieval-sourcing guarantee is unaffected.
"""

from __future__ import annotations

from pydantic import BaseModel

from agents.claims import gather_claims
from agents.deps import AgentDeps
from agents.types import Claim, ClaimStance

SYSTEM_PROMPT = """\
You are the Bear Agent. Build the strongest BEARISH investment thesis for the
given company, citing only evidence returned by the Retrieval Agent. Surface
declines, risks, and data-quality caveats. You may not invent weaknesses that
retrieval did not return; if the evidence is thin, say so.
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


def _summarise(ticker: str, claims: list[Claim]) -> str:
    if not claims:
        return (
            f"No retrieval-supported bearish evidence was found for {ticker}; "
            "the available filing is uniformly positive."
        )
    return (
        f"Bear case for {ticker} rests on {len(claims)} sourced point(s): "
        + "; ".join(c.text.rstrip(".") for c in claims)
        + "."
    )


class BearAgent:
    async def run(self, deps: AgentDeps, ticker: str) -> BearThesis:
        async with deps.session_factory() as session:
            claims = await gather_claims(
                deps, session, ticker, _BEAR_PROBES, ClaimStance.BEAR
            )
        return BearThesis(
            ticker=ticker, thesis_summary=_summarise(ticker, claims), claims=claims
        )
