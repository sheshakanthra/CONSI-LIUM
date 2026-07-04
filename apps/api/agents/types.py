"""Shared agent types.

A ``Claim`` is the unit that flows between agents. It is deliberately
*constructed only from a retrieval Answer*, so a claim can never carry text that
isn't backed by at least one citation — that's how "no unsourced claims" is
enforced structurally rather than by asking a model nicely.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from retrieval.types import Citation, Confidence


class ClaimStance(str, Enum):
    BULL = "bull"
    BEAR = "bear"


class Claim(BaseModel):
    """One evidence-backed assertion produced by bull/bear from retrieval."""

    id: str
    stance: ClaimStance
    # The answer text returned by retrieval — never free-authored by the agent.
    text: str
    # The question the agent asked retrieval to obtain this claim.
    probe: str
    confidence: Confidence
    # Non-empty by construction (claims without citations are dropped upstream).
    citations: list[Citation] = Field(min_length=1)
