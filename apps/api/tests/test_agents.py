"""End-to-end LangGraph research test on the sample ticker.

The reasoning agents now call Claude, so the LLM client is **mocked** with a
deterministic fake — tests stay hermetic, free, and reproducible (no API key, no
network). The fake:
  * for a thesis, echoes each provided evidence item back as a claim (so claims
    stay grounded and re-verifiable), and
  * for a fact-check adjudication, returns SUPPORTED.

We build the graph with fake deps and run it once, then assert:
  * the final ResearchNote is well-formed (types, non-empty summary, quant stub),
  * at least one claim went through the fact-checker with a REAL enum label,
  * the note only presents fact-checked claims, correctly partitioned, and
  * a claim citing evidence the LLM invented is DROPPED (sourcing guarantee).

Marked ``integration``: needs Postgres + the embedding model. Skips if the DB is
unreachable.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from sqlalchemy import select, text

from agents.bull_agent import BullAgent
from agents.deps import AgentDeps
from agents.fact_checker_agent import ClaimLabel, FactCheckReport
from agents.graph import build_research_graph
from agents.llm_client import LLMUsage
from agents.retrieval_agent import RetrievalAgent
from agents.synthesizer_agent import ResearchNote
from app.config import get_settings
from app.db import SessionLocal, engine
from ingestion import pipeline
from ingestion.generate_samples import generate_samples
from ingestion.models import Filing
from retrieval.indexer import build_index
from retrieval.schema import ensure_vector_schema

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]

_TABLES = ["transcript_segments", "transcripts", "filing_chunks", "filing_tables", "filings"]

_ZERO_USAGE = LLMUsage(model="fake", input_tokens=0, output_tokens=0, cost_usd=0.0)


class FakeLLM:
    """Deterministic, offline stand-in for the Claude client.

    Duck-types ``LLMClient.structured``: builds the requested schema directly,
    so it needs no knowledge of the concrete Pydantic classes.
    """

    def __init__(self, extra_bogus_claim: bool = False) -> None:
        # If True, thesis output also cites a nonexistent evidence id (E999),
        # which build_thesis must drop.
        self._bogus = extra_bogus_claim

    async def structured(self, *, system: str, user: str, schema, agent: str):
        name = schema.__name__
        if name == "ThesisDraft":
            pairs = re.findall(r"^(E\d+): (.*)$", user, re.M)
            claims = [{"evidence_id": eid, "claim": txt} for eid, txt in pairs]
            if self._bogus:
                claims.append({"evidence_id": "E999", "claim": "BOGUS unsourced claim"})
            obj = schema(thesis_summary=f"{agent} thesis ({len(pairs)} points)", claims=claims)
        elif name == "_LLMVerdict":
            obj = schema(label="SUPPORTED", rationale="mock adjudication")
        else:  # pragma: no cover - guards against an unmocked call
            raise AssertionError(f"unexpected schema for {agent}: {name}")
        return obj, _ZERO_USAGE


def _deps(llm) -> AgentDeps:
    return AgentDeps(retrieval=RetrievalAgent(), session_factory=SessionLocal, llm=llm)


async def _db_reachable() -> bool:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@pytest.fixture(scope="session", autouse=True)
async def _indexed_db():
    await engine.dispose()
    if not await _db_reachable():
        pytest.skip("Postgres not reachable (start docker compose)")

    settings = get_settings()
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    await pipeline.create_schema()
    await ensure_vector_schema()
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {', '.join(_TABLES)} RESTART IDENTITY CASCADE"))

    generate_samples(settings.filings_dir)
    async with SessionLocal() as session:
        await pipeline.ingest_filing(
            session, Path(settings.filings_dir) / "sample_filing_01.pdf", settings
        )
    async with SessionLocal() as session:
        await build_index(session)
    yield


@pytest.fixture(scope="session")
async def ticker() -> str:
    async with SessionLocal() as session:
        filing = (
            await session.execute(
                select(Filing).where(Filing.file_name == "sample_filing_01.pdf")
            )
        ).scalar_one()
    return filing.ticker


@pytest.fixture(scope="session")
async def state(ticker):
    """Run the whole graph once (with the mocked LLM) and share the final state."""
    graph = build_research_graph(_deps(FakeLLM()))
    return await graph.ainvoke({"ticker": ticker})


async def test_graph_runs_end_to_end(state, ticker):
    assert set(state) >= {"ticker", "bull", "bear", "quant", "fact_check", "note"}

    note = state["note"]
    assert isinstance(note, ResearchNote)
    assert note.ticker == ticker
    assert note.thesis_summary.strip()
    # Quant signal is present, real (Phase 4 — no longer a placeholder), and
    # well-formed.
    assert note.quant_signal.is_placeholder is False
    assert note.quant_signal.direction.value in {"bullish", "bearish", "neutral"}
    assert 0.0 <= note.quant_signal.confidence <= 1.0
    assert note.quant_signal.horizon.strip()
    assert note.quant_signal.reasoning.strip()
    assert len(note.quant_signal.series) > 0


async def test_fact_checker_labelled_at_least_one_claim(state):
    report: FactCheckReport = state["fact_check"]

    assert len(report.checked) >= 1
    # Every verdict is a real enum label — no free-text pass-through.
    for fc in report.checked:
        assert isinstance(fc.label, ClaimLabel)
    # At least one SUPPORTED (the sample filing has hard figures).
    assert any(fc.label is ClaimLabel.SUPPORTED for fc in report.checked)
    assert sum(report.counts.values()) == len(report.checked)


async def test_note_only_contains_factchecked_claims(state):
    note: ResearchNote = state["note"]
    report: FactCheckReport = state["fact_check"]

    n_supported = sum(1 for fc in report.checked if fc.label is ClaimLabel.SUPPORTED)
    assert len(note.key_supported_claims) == n_supported
    assert len(note.key_disputed_or_unverifiable_claims) == len(report.checked) - n_supported

    for claim in note.key_supported_claims:
        assert claim.citations, "supported claim missing a citation"
        assert claim.citations[0].source_id > 0


async def test_unsourced_llm_claim_is_dropped(ticker):
    """A claim citing evidence the LLM invented must be dropped, not passed through."""
    deps = _deps(FakeLLM(extra_bogus_claim=True))
    thesis = await BullAgent().run(deps, ticker)

    # The bogus claim (cites nonexistent E999) never makes it into the thesis.
    assert all("BOGUS" not in c.text for c in thesis.claims)
    # Every surviving claim carries a real retrieval citation.
    for c in thesis.claims:
        assert c.citations and c.citations[0].source_id > 0
