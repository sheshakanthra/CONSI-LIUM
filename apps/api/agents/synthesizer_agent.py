"""synthesizer_agent — assembles the final structured research note.

Consumes the bull thesis, bear thesis, fact-check report, and quant signal, and
emits a ``ResearchNote``. Its rule: **only fact-checked claims reach the note**,
partitioned by the fact-checker's verdict:
  * SUPPORTED               -> key_supported_claims
  * CONTRADICTED / UNVERIFIABLE -> key_disputed_or_unverifiable_claims (flagged)

This makes the note's integrity a property of the graph, not the phrasing: a
claim the fact-checker couldn't confirm is surfaced as disputed/unverifiable,
never quietly presented as fact. Citations are the de-duplicated independent
sources the fact-checker actually found.

LLM seam: ``_summary`` is where a ReasonerLLM would write the prose thesis from
the fact-checked claims + quant signal; the claim partitioning and citation list
stay deterministic so the note's guarantees hold regardless.
"""

from __future__ import annotations

from pydantic import BaseModel

from agents.bear_agent import BearThesis
from agents.bull_agent import BullThesis
from agents.fact_checker_agent import ClaimLabel, FactCheckReport
from agents.quant_agent import QuantDirection, QuantSignal
from agents.types import ClaimStance
from retrieval.types import Citation

SYSTEM_PROMPT = """\
You are the Synthesizer. Combine the bull thesis, bear thesis, fact-check report,
and quant signal into a single structured research note. Present only
fact-checked claims: report SUPPORTED claims as the thesis, and explicitly flag
CONTRADICTED/UNVERIFIABLE claims as disputed. Never present an unverified claim as
established fact. Include a de-duplicated citation list.
"""


class NoteClaim(BaseModel):
    text: str
    stance: ClaimStance
    label: ClaimLabel
    citations: list[Citation]


class ResearchNote(BaseModel):
    """The final deliverable — synthesizer output schema."""

    ticker: str
    thesis_summary: str
    key_supported_claims: list[NoteClaim]
    key_disputed_or_unverifiable_claims: list[NoteClaim]
    quant_signal: QuantSignal
    citations: list[Citation]


def _dedup_citations(citations: list[Citation]) -> list[Citation]:
    seen: set[tuple[str, int]] = set()
    unique: list[Citation] = []
    for c in citations:
        key = (c.source_type, c.source_id)
        if key not in seen:
            seen.add(key)
            unique.append(c)
    return unique


def _qualitative_stance(n_bull: int, n_bear: int) -> QuantDirection:
    """Reduce the fact-checked bull/bear balance to a single directional lean.

    This is what the quant signal is compared *against* — the qualitative thesis
    reads bullish if more supported claims are bull-side, bearish if more are
    bear-side, otherwise neutral/balanced.
    """
    if n_bull > n_bear:
        return QuantDirection.BULLISH
    if n_bear > n_bull:
        return QuantDirection.BEARISH
    return QuantDirection.NEUTRAL


def _quant_agreement(qualitative: QuantDirection, quant: QuantSignal) -> str:
    """One sentence on whether the quant signal agrees with the thesis.

    Kept explicit (same spirit as the placeholder did) so the reader always sees
    where the price-based signal and the narrative diverge — a disagreement is
    signal, not something to paper over.
    """
    q = quant.direction
    conf = f"{quant.confidence:.0%} confidence over {quant.horizon}"
    if q is QuantDirection.NEUTRAL or qualitative is QuantDirection.NEUTRAL:
        return (
            f"Quant signal is {q.value} ({conf}); the qualitative thesis is "
            f"{qualitative.value} — no strong directional (dis)agreement to flag."
        )
    if q is qualitative:
        return (
            f"Quant signal is {q.value} ({conf}), AGREEING with the "
            f"{qualitative.value} qualitative thesis — the price trend corroborates "
            "the narrative."
        )
    return (
        f"Quant signal is {q.value} ({conf}), DISAGREEING with the "
        f"{qualitative.value} qualitative thesis — the price trend and the "
        "fundamental narrative point opposite ways; treat with caution."
    )


def _summary(
    ticker: str, supported: list[NoteClaim], disputed: list[NoteClaim], quant: QuantSignal
) -> str:
    n_bull = sum(1 for c in supported if c.stance is ClaimStance.BULL)
    n_bear = sum(1 for c in supported if c.stance is ClaimStance.BEAR)
    parts = [
        f"{ticker}: {len(supported)} fact-checked claim(s) supported "
        f"({n_bull} bull / {n_bear} bear), {len(disputed)} disputed or unverifiable."
    ]
    if disputed:
        parts.append(
            "Disputed/unverifiable items are flagged and excluded from the core thesis."
        )
    parts.append(_quant_agreement(_qualitative_stance(n_bull, n_bear), quant))
    parts.append("Quant is a supporting technical signal, not investment advice.")
    return " ".join(parts)


class SynthesizerAgent:
    async def run(
        self,
        ticker: str,
        bull: BullThesis,
        bear: BearThesis,
        fact_check: FactCheckReport,
        quant: QuantSignal,
    ) -> ResearchNote:
        supported: list[NoteClaim] = []
        disputed: list[NoteClaim] = []

        for fc in fact_check.checked:
            note_claim = NoteClaim(
                text=fc.claim_text,
                stance=fc.stance,
                label=fc.label,
                citations=[fc.evidence] if fc.evidence else [],
            )
            if fc.label is ClaimLabel.SUPPORTED:
                supported.append(note_claim)
            else:
                disputed.append(note_claim)

        citations = _dedup_citations(
            [c for nc in supported for c in nc.citations]
        )
        return ResearchNote(
            ticker=ticker,
            thesis_summary=_summary(ticker, supported, disputed, quant),
            key_supported_claims=supported,
            key_disputed_or_unverifiable_claims=disputed,
            quant_signal=quant,
            citations=citations,
        )
