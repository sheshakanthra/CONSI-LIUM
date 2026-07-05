"""Explicit, typed graph state.

WHY a TypedDict of concrete Pydantic outputs (not an implicit chain): LangGraph
threads this dict through every node, and each node writes a *distinct* key. That
makes the data flow legible and lets independent nodes (bull/bear/quant) run in
the same super-step without clobbering each other — no custom reducer needed
because there are no key collisions.
"""

from __future__ import annotations

from typing import TypedDict

from agents.bear_agent import BearThesis
from agents.bull_agent import BullThesis
from agents.fact_checker_agent import FactCheckReport
from agents.quant_agent import QuantSignal
from agents.synthesizer_agent import ResearchNote


class ResearchState(TypedDict, total=False):
    # Input.
    ticker: str
    # Filled by nodes (each key by exactly one node).
    bull: BullThesis
    bear: BearThesis
    quant: QuantSignal
    fact_check: FactCheckReport
    note: ResearchNote
