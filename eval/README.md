# eval

RAGAS + custom golden-set evaluation harness and the CI quality gate
(CLAUDE.md Part C). See [`../docs/phase5-eval.md`](../docs/phase5-eval.md) for
methodology and measured results.

## Layout

- `golden_set/` — curated, verified Q&A fixtures (`golden_set.json`) + schema
  docs. Covers Document QA, Table QA, refusal, and full `/research` runs.
- `scripts/`
  - `run_golden_eval.py` — deterministic gate (no LLM): answer + citation +
    refusal correctness. The hard CI gate.
  - `run_ragas.py` — RAGAS semantic metrics (faithfulness / answer relevancy /
    context precision) via the Groq judge + bge-small embeddings.
  - `eval_factchecker.py` — feeds known-true/false/unverifiable claims to the
    fact-checker and scores the labels (the core differentiator).
  - `_evalcommon.py` — shared path/golden-set bootstrap.
- `requirements-eval.txt` — RAGAS deps, installed in their **own** env (RAGAS's
  `langchain-core` pin conflicts with LangGraph; RAGAS only needs retrieval).

## Running locally (against docker-compose)

```bash
# 1. bring up db + api and index the sample corpus
docker compose up -d
docker compose exec api python -m ingestion.generate_samples
docker compose exec api python -m ingestion.run filings
docker compose exec api python -m retrieval.index

# 2. deterministic gate (no LLM key needed)
docker compose exec api python /app/../eval/scripts/run_golden_eval.py --skip-research
#    (or copy eval/ in and run with PYTHONPATH=/app; see docs/phase5-eval.md)

# 3. LLM-backed gates (need GROQ_API_KEY in the container env)
docker compose exec api python eval/scripts/eval_factchecker.py
```

CI runs all of this automatically on every PR — see
[`../.github/workflows/eval.yml`](../.github/workflows/eval.yml).
