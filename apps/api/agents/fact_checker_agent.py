"""fact_checker_agent — independent verification of every bull/bear claim.

This is the project's core differentiator, so its method is explicit:

  For each claim, the fact-checker issues its OWN fresh retrieval query — using
  the *claim's text* as the query, NOT the probe that produced it and NOT the
  citation bull/bear attached. It then compares the independently retrieved
  evidence to the claim and assigns exactly one label:

    SUPPORTED     — independent retrieval returns evidence agreeing with the claim
    CONTRADICTED  — independent retrieval returns a conflicting structured figure
    UNVERIFIABLE  — independent retrieval can't find supporting evidence

The independent re-query is unchanged from the deterministic version. What's new:
the **judgment call** is escalated to Claude when the re-query result isn't a
clean exact match. Clear cases stay deterministic (and free):
  * re-query insufficient        -> UNVERIFIABLE (no LLM)
  * exact numeric value matches  -> SUPPORTED    (no LLM)
  * table returns a different num -> CONTRADICTED (no LLM)
Everything else (paraphrases, narrative claims) goes to the LLM, which returns
one ``ClaimLabel`` + rationale.

The output schema (``ClaimLabel`` enum on every ``FactCheckedClaim``) makes a
label mandatory — there is no free-text field a model (or this code) could use to
dodge the decision. Each verdict carries the independently-found source, not the
claim's original citation, so "supported" means "re-confirmed", not "self-cited".

WHY re-query by claim text (independence): replaying the original probe would
just re-run the same lookup. Querying the claim's assertion instead is a genuine
second path to the evidence — closer to how a human checker re-derives a number.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Literal

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from agents.deps import AgentDeps
from agents.types import Claim, ClaimStance
from retrieval.types import Answer, Citation, QAPath

SYSTEM_PROMPT = """\
You are the Fact Checker. You are given one claim and a piece of evidence that was
retrieved INDEPENDENTLY (not the claim's own citation). Decide exactly one label:
- SUPPORTED: the evidence substantiates the claim.
- CONTRADICTED: the evidence directly conflicts with the claim.
- UNVERIFIABLE: the evidence is unrelated or insufficient to judge the claim.
Base the decision only on the given evidence. Never invent facts.
"""

class ClaimLabel(str, Enum):
    SUPPORTED = "SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    UNVERIFIABLE = "UNVERIFIABLE"


class FactCheckedClaim(BaseModel):
    """One claim + its mandatory verdict. No free-text pass-through."""

    claim_id: str
    claim_text: str
    stance: ClaimStance
    label: ClaimLabel
    # The INDEPENDENTLY retrieved source backing the verdict (None if none found).
    evidence: Citation | None = None
    evidence_text: str | None = None
    rationale: str


class FactCheckReport(BaseModel):
    """Fact checker output schema."""

    ticker: str
    checked: list[FactCheckedClaim]
    # Convenience tally per label, e.g. {"SUPPORTED": 4, "UNVERIFIABLE": 1}.
    counts: dict[str, int]


class _LLMVerdict(BaseModel):
    """The LLM's structured adjudication (schema sent to Claude)."""

    label: Literal["SUPPORTED", "CONTRADICTED", "UNVERIFIABLE"]
    rationale: str


def _claim_value(text: str) -> str | None:
    """Extract the asserted value from a structured claim like '... is 1,245.'."""
    m = re.search(r"\bis\s+(.+?)\.?$", text.strip())
    return m.group(1).strip().rstrip(".") if m else None


def _clean_match(claim: Claim, fresh: Answer) -> tuple[ClaimLabel, str] | None:
    """Deterministic verdict for unambiguous cases; None => escalate to the LLM.

    Returns a label only when the outcome is clear without judgment:
    insufficient evidence, an exact numeric-value match, or a structured table
    figure that disagrees. Paraphrases and narrative claims return None.
    """
    if not fresh.sufficient:
        return ClaimLabel.UNVERIFIABLE, "independent retrieval found no supporting evidence"

    value = _claim_value(claim.text)
    if value is not None:
        if value in fresh.answer:
            return ClaimLabel.SUPPORTED, f"independent retrieval reproduced the value {value!r}"
        if fresh.path is QAPath.TABLE:
            return (
                ClaimLabel.CONTRADICTED,
                f"independent table lookup returned {fresh.answer!r}, not {value!r}",
            )
    return None  # not a clean match -> let the LLM judge


def _verdict_prompt(claim: Claim, fresh: Answer) -> str:
    source = fresh.citations[0] if fresh.citations else None
    src = (
        f"{source.source_type} id={source.source_id}, page {source.page_number}"
        if source
        else "unknown"
    )
    return (
        f"CLAIM ({claim.stance.value}): {claim.text}\n\n"
        f"INDEPENDENTLY RETRIEVED EVIDENCE (source: {src}):\n{fresh.answer}\n\n"
        "Does the evidence support, contradict, or fail to verify the claim?"
    )


class FactCheckerAgent:
    async def run(
        self, deps: AgentDeps, ticker: str, claims: list[Claim]
    ) -> FactCheckReport:
        checked: list[FactCheckedClaim] = []
        counts: dict[str, int] = {label.value: 0 for label in ClaimLabel}

        # Own session; independent of whatever bull/bear used.
        async with deps.session_factory() as session:
            for claim in claims:
                fresh = await self._recheck(deps, session, ticker, claim)

                clean = _clean_match(claim, fresh)
                if clean is not None:
                    label, rationale = clean
                else:
                    # Not a clean match -> Claude adjudicates the judgment call.
                    verdict, _usage = await deps.llm.structured(
                        system=SYSTEM_PROMPT,
                        user=_verdict_prompt(claim, fresh),
                        schema=_LLMVerdict,
                        agent="fact_checker_agent",
                    )
                    label = ClaimLabel(verdict.label)
                    rationale = f"LLM: {verdict.rationale}"

                counts[label.value] += 1
                evidence = fresh.citations[0] if (fresh.sufficient and fresh.citations) else None
                checked.append(
                    FactCheckedClaim(
                        claim_id=claim.id,
                        claim_text=claim.text,
                        stance=claim.stance,
                        label=label,
                        evidence=evidence,
                        evidence_text=fresh.answer if fresh.sufficient else None,
                        rationale=rationale,
                    )
                )

        return FactCheckReport(ticker=ticker, checked=checked, counts=counts)

    async def _recheck(
        self, deps: AgentDeps, session: AsyncSession, ticker: str, claim: Claim
    ) -> Answer:
        # Independent query keyed on the claim's assertion, not its probe.
        return await deps.retrieval.retrieve(session, ticker, claim.text)
