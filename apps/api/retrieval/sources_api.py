"""FastAPI citation-resolution endpoint.

GET /sources/{source_type}/{source_id}  ->  SourceDocument

The dashboard's citation drill-down calls this: a ``Citation`` on a research
note carries only a pointer, and this turns that pointer back into the evidence
a reader can actually check.

WHY a separate router from /qa: /qa *searches* (loads an embedding model, ranks
candidates); this only dereferences a primary key. Keeping them apart means the
citation panel never pays for — or waits on — the embedding model.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from retrieval.sources import SourceDocument, SourceKind, resolve_source

router = APIRouter(prefix="/sources", tags=["sources"])


@router.get("/{source_type}/{source_id}", response_model=SourceDocument)
async def get_source(
    source_type: SourceKind,
    source_id: int = Path(ge=1, description="filing_chunks.id or filing_tables.id"),
    session: AsyncSession = Depends(get_session),
) -> SourceDocument:
    """Resolve one citation pointer to its source evidence.

    404 on an unknown id — an unresolvable citation is a real, reportable
    condition ("no silent failure"), not an empty body the UI would render as a
    blank panel.
    """
    doc = await resolve_source(session, source_type, source_id)
    if doc is None:
        raise HTTPException(
            status_code=404,
            detail=f"no {source_type.value} source with id {source_id}",
        )
    return doc
