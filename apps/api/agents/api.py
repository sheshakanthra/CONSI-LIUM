"""FastAPI research endpoint.

GET /research/{ticker}  ->  ResearchNote

Runs the full LangGraph research graph and returns the synthesizer's structured
note. Retrieval must have been indexed (``python -m retrieval.index``) for the
ticker to have evidence; an unknown ticker yields a note with empty claims and a
neutral quant stub rather than an error.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from agents.graph import run_research
from agents.synthesizer_agent import ResearchNote

router = APIRouter(prefix="/research", tags=["research"])


@router.get("/{ticker}", response_model=ResearchNote)
async def research(ticker: str) -> ResearchNote:
    state = await run_research(ticker.upper())
    note = state.get("note")
    if note is None:  # graph invariant broken — surface loudly, don't return null
        raise HTTPException(status_code=500, detail="research graph produced no note")
    return note
