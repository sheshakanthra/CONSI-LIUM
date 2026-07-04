"""Shared claim-gathering helper for bull/bear agents.

Both agents do the same mechanical thing — ask retrieval a stance-specific set of
probe questions and keep the sourced answers — so that logic lives here. The
*charter* (which probes, what the thesis argues) stays in each agent's own file;
this is just the plumbing that guarantees every kept claim is retrieval-backed.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from agents.deps import AgentDeps
from agents.types import Claim, ClaimStance


async def gather_claims(
    deps: AgentDeps,
    session: AsyncSession,
    ticker: str,
    probes: list[str],
    stance: ClaimStance,
) -> list[Claim]:
    """Run each probe through retrieval; keep sourced, deduplicated answers."""
    claims: list[Claim] = []
    seen: set[str] = set()

    for probe in probes:
        answer = await deps.retrieval.retrieve(session, ticker, probe)
        # Drop anything retrieval couldn't support — this is the guardrail
        # against unsourced claims.
        if not answer.sufficient or not answer.citations:
            continue
        key = answer.answer.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        claims.append(
            Claim(
                id=f"{stance.value}-{len(claims) + 1}",
                stance=stance,
                text=answer.answer,
                probe=probe,
                confidence=answer.confidence,
                citations=answer.citations,
            )
        )
    return claims
