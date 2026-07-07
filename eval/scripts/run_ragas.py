"""RAGAS eval over the golden set — semantic RAG quality metrics.

Scores the Phase 2 retrieval layer on the answerable golden entries
(``table_qa`` + ``document_qa``) with three RAGAS metrics:

  * faithfulness       — is every statement in the answer grounded in the
    retrieved context? (the hallucination guard)
  * answer_relevancy   — does the answer actually address the question?
  * context_precision  — were the retrieved contexts relevant to the reference?

WHY RAGAS runs in its OWN environment (see eval/requirements-eval.txt): RAGAS
pins ``langchain-core`` to the 0.3 line, which conflicts with the LangGraph pin
the agent service uses. They can't share one venv — but RAGAS only needs the
*retrieval* path (QAService), not the graph, so this is a clean split, not a
compromise. The deterministic gate (run_golden_eval.py) has no such dependency
and covers every entry.

Judge + embeddings: the project's own Groq model (OpenAI-compatible endpoint) as
the LLM judge and the same bge-small fastembed model used in retrieval — so the
eval uses the exact embedding space the system retrieves in, and needs no extra
paid API.

Run (inside the api container, with ragas installed and a working key):
    PYTHONPATH=/app python run_ragas.py --golden-set /tmp/golden_set.json --limit 12
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from _evalcommon import bootstrap_api_path, load_entries

bootstrap_api_path()

from sqlalchemy import select  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from ingestion.models import FilingChunk, FilingTable  # noqa: E402
from retrieval.retriever import Retriever  # noqa: E402
from retrieval.service import QAService  # noqa: E402


def _serialize_table(table: FilingTable) -> str:
    header = " | ".join(str(c) for c in table.columns)
    body = "\n".join(" | ".join(str(c) for c in row) for row in table.rows)
    return f"{header}\n{body}"


async def _build_samples(entries: list[dict], limit: int | None) -> list[dict]:
    """Produce RAGAS single-turn rows from real system output + contexts."""
    svc = QAService()
    retriever = Retriever()
    answerable = [e for e in entries if e["category"] in ("table_qa", "document_qa")]
    if limit:
        # Interleave the two categories/tickers so a subset stays representative.
        answerable = sorted(answerable, key=lambda e: (e["id"].split("-")[1], e["category"]))
        answerable = answerable[:limit]

    samples: list[dict] = []
    async with SessionLocal() as session:
        for e in answerable:
            ans = await svc.answer_question(session, e["question"], e["ticker"])

            if e["category"] == "document_qa":
                # Real ranked retrieval candidates = the honest context set.
                chunks = await retriever.retrieve(session, e["ticker"], e["question"])
                contexts = [c.text for c in chunks] or [ans.answer]
            else:  # table_qa -> the cited structured table, serialized
                contexts = []
                if ans.citations:
                    tbl = (
                        await session.execute(
                            select(FilingTable).where(FilingTable.id == ans.citations[0].source_id)
                        )
                    ).scalar_one_or_none()
                    if tbl is not None:
                        contexts = [_serialize_table(tbl)]
                if not contexts:
                    contexts = [ans.answer]

            samples.append({
                "id": e["id"],
                "user_input": e["question"],
                "response": ans.answer,
                "retrieved_contexts": contexts,
                "reference": e["ground_truth"],
            })
    return samples


def _make_llm_and_embeddings():
    """Groq (OpenAI-compatible) judge + bge-small fastembed, wrapped for RAGAS."""
    from langchain_openai import ChatOpenAI
    from langchain_community.embeddings import FastEmbedEmbeddings
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.llms import LangchainLLMWrapper

    settings = get_settings()
    if not settings.groq_api_key:
        raise SystemExit(
            "GROQ_API_KEY is empty — RAGAS needs a working LLM judge. "
            "Set it in the environment before running."
        )
    chat = ChatOpenAI(
        model=settings.groq_model,
        api_key=settings.groq_api_key,
        base_url="https://api.groq.com/openai/v1",
        temperature=0.0,
        timeout=60,
        max_retries=3,
    )
    embed = FastEmbedEmbeddings(model_name=settings.embedding_model)
    return LangchainLLMWrapper(chat), LangchainEmbeddingsWrapper(embed)


def _evaluate(samples: list[dict], max_workers: int) -> dict:
    from ragas import EvaluationDataset, RunConfig, evaluate
    from ragas.metrics import (
        Faithfulness,
        LLMContextPrecisionWithReference,
        ResponseRelevancy,
    )

    llm, embeddings = _make_llm_and_embeddings()
    dataset = EvaluationDataset.from_list(
        [{k: s[k] for k in ("user_input", "response", "retrieved_contexts", "reference")}
         for s in samples]
    )
    metrics = [
        Faithfulness(llm=llm),
        ResponseRelevancy(llm=llm, embeddings=embeddings),
        LLMContextPrecisionWithReference(llm=llm),
    ]
    result = evaluate(
        dataset=dataset,
        metrics=metrics,
        llm=llm,
        embeddings=embeddings,
        run_config=RunConfig(max_workers=max_workers, timeout=120),
        raise_exceptions=False,
        show_progress=True,
    )
    df = result.to_pandas()
    metric_cols = [c for c in df.columns
                   if c in ("faithfulness", "answer_relevancy", "response_relevancy",
                            "llm_context_precision_with_reference", "context_precision")]
    scores = {c: float(df[c].mean(skipna=True)) for c in metric_cols}
    per_sample = []
    for s, (_, row) in zip(samples, df.iterrows()):
        per_sample.append({"id": s["id"],
                           **{c: (None if row[c] != row[c] else float(row[c])) for c in metric_cols}})
    return {"scores": scores, "per_sample": per_sample, "n": len(samples)}


def main() -> int:
    p = argparse.ArgumentParser(description="RAGAS eval over the golden set")
    p.add_argument("--golden-set", default=None)
    p.add_argument("--limit", type=int, default=None,
                   help="cap number of samples (rate/cost control on free LLM tiers)")
    p.add_argument("--max-workers", type=int, default=2)
    p.add_argument("--min-faithfulness", type=float, default=0.80)
    p.add_argument("--json", dest="as_json", action="store_true")
    args = p.parse_args()

    entries = load_entries(args.golden_set)
    samples = asyncio.run(_build_samples(entries, args.limit))
    print(f"[ragas] scoring {len(samples)} answerable samples ...", file=sys.stderr)

    summary = _evaluate(samples, args.max_workers)

    if args.as_json:
        print(json.dumps(summary, indent=2))
    else:
        print("RAGAS scores (mean over samples)")
        print("=" * 50)
        for name, val in summary["scores"].items():
            print(f"  {name:<38} {val:.3f}")
        print("-" * 50)
        print(f"  samples: {summary['n']}")

    faith = summary["scores"].get("faithfulness")
    if faith is not None and faith < args.min_faithfulness:
        print(f"\nFAILED gate: faithfulness {faith:.3f} < {args.min_faithfulness:.2f}",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
