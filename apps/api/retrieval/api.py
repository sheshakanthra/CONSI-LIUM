"""FastAPI QA endpoint.

POST /qa  { "question": ..., "ticker": ... }  ->  Answer

The heavy embedding model is loaded once (lazily, on first request) via a cached
service getter, not at import/startup — so the app boots fast and only pays the
model-load cost if QA is actually used.
"""

from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from retrieval.service import QAService
from retrieval.types import Answer

router = APIRouter(prefix="/qa", tags=["qa"])


class QARequest(BaseModel):
    question: str = Field(min_length=1)
    ticker: str = Field(min_length=1, description="company ticker to scope retrieval")


@lru_cache(maxsize=1)
def _get_service() -> QAService:
    """One shared service (and embedding model) per process."""
    return QAService()


@router.post("", response_model=Answer)
async def qa(req: QARequest, session: AsyncSession = Depends(get_session)) -> Answer:
    service = _get_service()
    return await service.answer_question(session, req.question, req.ticker.upper())
