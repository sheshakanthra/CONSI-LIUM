"""LLM-backed thesis construction shared by the bull and bear agents.

The flow, and where the sourcing guarantee lives:

1. **Gather candidate evidence** from retrieval (stance-specific probes). Each
   kept item is a real retrieval ``Answer`` with citations, tagged ``E1``, ``E2``…
2. **Ask Claude** (with the agent's scoped system prompt) to build the thesis
   from *only* that evidence: a ``thesis_summary`` plus claims, each claim
   citing exactly one evidence id.
3. **Re-attach citations from OUR evidence**, never from the model. A claim that
   cites an evidence id we didn't provide — i.e. an unsourced/hallucinated
   claim — is **dropped**, not passed through. This is why the Claim schema's
   ``citations: min_length=1`` guarantee still holds after adding the LLM: the
   citation can only ever come from a retrieval Answer.

The LLM output schema here is deliberately minimal (`evidence_id` + `claim`
text) so it stays a valid Anthropic structured-output schema and so the mapping
back to real citations is unambiguous.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from agents.deps import AgentDeps
from agents.types import Claim, ClaimStance
from retrieval.types import Answer

logger = logging.getLogger("consilium.agents.reasoning")


class ThesisClaimDraft(BaseModel):
    """One LLM-proposed claim: which evidence it rests on + how it's phrased."""

    evidence_id: str = Field(description="the id of the single evidence item this claim cites, e.g. E2")
    claim: str = Field(description="the claim, grounded strictly in the cited evidence")


class ThesisDraft(BaseModel):
    """The LLM's structured thesis output (schema sent to Claude)."""

    thesis_summary: str
    claims: list[ThesisClaimDraft]


@dataclass
class EvidenceItem:
    id: str
    probe: str
    answer: Answer


async def gather_evidence(
    deps: AgentDeps, session: AsyncSession, ticker: str, probes: list[str]
) -> list[EvidenceItem]:
    """Run each probe through retrieval; keep sourced, deduplicated answers."""
    items: list[EvidenceItem] = []
    seen: set[str] = set()
    for probe in probes:
        answer = await deps.retrieval.retrieve(session, ticker, probe)
        if not answer.sufficient or not answer.citations:
            continue
        key = answer.answer.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        items.append(EvidenceItem(id=f"E{len(items) + 1}", probe=probe, answer=answer))
    return items


def _format_prompt(ticker: str, stance: ClaimStance, evidence: list[EvidenceItem]) -> str:
    lines = "\n".join(f"{item.id}: {item.answer.answer}" for item in evidence)
    return (
        f"Company ticker: {ticker}\n\n"
        f"Retrieved evidence (each line is 'ID: text'):\n{lines}\n\n"
        f"Build the strongest {stance.value.upper()} thesis for {ticker} using ONLY the "
        "evidence above. Return a concise thesis_summary and a list of claims. Each claim "
        "must cite exactly one evidence id (the 'E#' label) in its evidence_id field, and "
        "must not state any figure or fact that is not present in that cited evidence. "
        "Omit a point rather than citing evidence that doesn't support it."
    )


async def build_thesis(
    deps: AgentDeps,
    ticker: str,
    probes: list[str],
    stance: ClaimStance,
    system_prompt: str,
) -> tuple[str, list[Claim]]:
    """Return (thesis_summary, claims) for a stance, via retrieval + Claude."""
    async with deps.session_factory() as session:
        evidence = await gather_evidence(deps, session, ticker, probes)

    if not evidence:
        return (
            f"No retrieval-supported {stance.value} evidence was found for {ticker}.",
            [],
        )

    draft, _usage = await deps.llm.structured(
        system=system_prompt,
        user=_format_prompt(ticker, stance, evidence),
        schema=ThesisDraft,
        agent=f"{stance.value}_agent",
    )

    by_id = {item.id: item for item in evidence}
    claims: list[Claim] = []
    for proposed in draft.claims:
        item = by_id.get(proposed.evidence_id)
        text = proposed.claim.strip()
        if item is None or not text:
            # Unsourced (cites evidence we never provided) or empty -> drop it.
            logger.warning(
                "dropping %s claim citing unknown/empty evidence %r",
                stance.value, proposed.evidence_id,
            )
            continue
        claims.append(
            Claim(
                id=f"{stance.value}-{len(claims) + 1}",
                stance=stance,
                text=text,
                probe=item.probe,
                confidence=item.answer.confidence,
                citations=item.answer.citations,  # real citation, from retrieval
            )
        )

    return draft.thesis_summary.strip(), claims
