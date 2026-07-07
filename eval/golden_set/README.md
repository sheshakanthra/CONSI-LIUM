# Golden set

Hand-written, verified Q&A fixtures for the CONSILIUM eval harness
(`../scripts/`). Every entry in [`golden_set.json`](./golden_set.json) was run
against the live retrieval / agent stack on the two synthetic sample filings and
its `answer_contains` / `expected_citation` reflect what the system actually
returns — this is ground truth, not aspiration.

## Corpus

| ticker | company | filing |
|--------|---------|--------|
| `ACME` | Acme Industries Ltd. | `sample_filing_01.pdf` |
| `GLOBEX` | Globex Corporation Ltd. | `sample_filing_02.pdf` |

Regenerate + ingest the corpus with:

```bash
docker compose exec api python -m ingestion.generate_samples
docker compose exec api python -m ingestion.run filings
docker compose exec api python -m retrieval.index
```

## Entry schema

```jsonc
{
  "id": "tq-acme-rev-q1fy27",        // stable unique id
  "category": "table_qa",            // table_qa | document_qa | insufficient | research
  "ticker": "ACME",
  "question": "What was revenue in Q1 FY27?",
  "ground_truth": "Revenue for Q1 FY27 was 1,245 (INR crore).", // canonical answer (RAGAS)
  "answer_contains": ["1,245"],      // case-insensitive substrings the answer MUST contain
  "expected_citation": {             // null for `insufficient`
    "source_type": "table",          // table | chunk | any
    "page": 1
  },
  "sufficient": true,                // false => system must refuse (no citation)
  // research-only:
  "min_supported_claims": 1,
  "require_citations": true,
  "require_quant": true
}
```

### Why these fields

- **`answer_contains` (substrings), not exact string** — the document path is
  *extractive*: it returns a text window around the match, so an exact-string
  oracle would be brittle. Substring containment of the load-bearing token
  (a figure, a keyword) is the honest correctness signal. `ground_truth` keeps
  the full canonical answer for RAGAS's semantic metrics.
- **`expected_citation` by `source_type` + `page`, not by row id** — ids shift
  on re-ingest; the *provenance* (did it cite a table vs a chunk, on the right
  page) is what we actually want to hold stable.
- **`insufficient` entries** — a RAG system is only trustworthy if it refuses
  when the corpus can't answer. These assert the canonical refusal and, crucially,
  that **no citation** is emitted. They are the counterweight to answerable
  recall and feed the "refusal accuracy" metric.

## Category breakdown

| category | count | scored by |
|----------|-------|-----------|
| `table_qa` | 17 | `run_golden_eval.py` (exact) + `run_ragas.py` (semantic) |
| `document_qa` | 7 | `run_golden_eval.py` (exact) + `run_ragas.py` (semantic) |
| `insufficient` | 8 | `run_golden_eval.py` (refusal accuracy) |
| `research` | 2 | `run_golden_eval.py` (structural: claims + citations + quant) |

See [`../../docs/phase5-eval.md`](../../docs/phase5-eval.md) for methodology and
the latest measured numbers.
