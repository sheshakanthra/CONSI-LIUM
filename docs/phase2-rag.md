# Phase 2 — Retrieval / RAG Layer

> Design note for the retrieval phase. Per CLAUDE.md, each phase ships a short
> markdown note capturing the design decisions.

## What this phase delivers

A question-answering layer under `apps/api/retrieval/` over the Phase 1 data:

```
question + ticker
  └─ router (heuristic)
        ├─ TABLE path ──▶ table_qa: exact cell lookup in filing_tables
        └─ DOCUMENT path ▶ retriever (hybrid) ─▶ extractive answerer
  ▶ Answer { answer, path, citations[], confidence, sufficient }
```

Run it:

```bash
docker compose exec api python -m retrieval.index          # embed + backfill
curl -X POST localhost:8000/qa -H 'content-type: application/json' \
     -d '{"question":"What was revenue in Q1 FY27?","ticker":"ACME"}'
docker compose exec api pytest tests/test_retrieval.py -v  # 5 Q&A pairs
```

## Embedding model — the cost/latency/quality call

**Choice: `BAAI/bge-small-en-v1.5` (384-dim) via `fastembed` (ONNX Runtime).**

| Axis | Reasoning |
|---|---|
| **Quality** | bge-small-en-v1.5 is a top *small* retrieval model on MTEB and is trained with query/passage asymmetry that suits QA. Big enough to be good, small enough to be free-to-run. |
| **Cost** | Runs locally → **zero per-embedding API cost**. Right for a portfolio project that re-embeds often while iterating. No secret to manage. |
| **Latency / footprint** | 384 dims ⇒ small pgvector rows and cheap distance math. Via **fastembed** it runs on the `onnxruntime` already present from faster-whisper, **avoiding ~1 GB of PyTorch**. Embeds the sample corpus in well under a second on CPU. |
| **Asymmetry** | Passages embed as-is; queries get bge's search-instruction prefix (`embed_query` uses fastembed's `query_embed`). |

Rejected alternatives: `all-MiniLM-L6-v2` (also 384-dim but weaker retrieval
quality); OpenAI `text-embedding-3-*` (better quality but per-call cost, a
network dependency, and a key to manage — unjustified at portfolio scale);
`bge-base/large` (higher quality, but slower and heavier for marginal gain here).

The embedding dimension lives in one place (`settings.embedding_dim`) and drives
both the `vector(384)` column and the embedder, so they can't drift.

## Hybrid retrieval (per ticker)

`retriever.py` runs two signals over `filing_chunks`, always filtered to one
`filings.ticker`:

1. **Vector** — pgvector cosine distance (`<=>`) on the query embedding.
2. **Keyword** — Postgres full-text (`to_tsvector @@ plainto_tsquery`, ranked by
   `ts_rank`). Computed on the fly (no stored tsvector) — fine at this scale.

**Fusion = Reciprocal Rank Fusion.** The two scores are on incomparable scales
(cosine vs ts_rank), so we fuse by *rank* — each hit contributes `1/(rrf_k +
rank)` from each list. No cross-scale calibration, order-robust, and the keyword
list is a genuine fallback when embeddings are missing or the match is lexical
(numbers, proper nouns). The winning chunk's cosine similarity is still carried
through to drive confidence.

**No ANN index.** At portfolio corpus size, exact search is instant and avoids
the recall tuning an ivfflat/hnsw index needs. `docs` notes this as the first
thing to add when the corpus grows.

## Routing: structured-number vs narrative

`router.py` is a **cheap heuristic** (as the brief asked): a keyword test over a
curated set of finance-metric terms (`revenue`, `ebitda`, `eps`, `margin`,
`yoy`, …) plus a few phrases. A hit → TABLE path; otherwise DOCUMENT. We
deliberately exclude words like *dividend* — a dividend *recommendation* is
narrative, not a cell to look up.

The seam is a single function returning a `QAPath`, so it can be swapped for a
zero-shot classifier (small cross-encoder or an LLM call) later without touching
callers. The service also **falls back** to the document path if the table path
finds no figure, so a mis-route never strands a valid answer.

## Table QA — answering from structured data

`table_qa.py` is the payoff of keeping tables structured in Phase 1. It picks the
metric **row** whose label best overlaps the question (with a few finance
synonyms) and the **column** whose header best matches (defaulting to the most
recent period), then returns the **exact cell** with a citation to the table id
and page. No metric row match → "insufficient evidence" rather than a guess.

## Answering + the LLM seam

Per the decision recorded with the user, answering is **extractive** now: the
answer is the retrieved sentence best overlapping the question's content words,
so it's always grounded in a specific chunk. This needs no API key, runs offline
in the docker stack, and makes citation tests deterministic.

`AnswerSynthesizer` is the **swap point**: a future `ClaudeAnswerer`
implementing `synthesize(question, contexts)` can generate fluent prose from the
same retrieved contexts without changing the router, retriever, service, or
citation plumbing.

## Every answer's contract (`retrieval/types.py`, Pydantic)

```
Answer { question, ticker, path, answer,
         sufficient: bool,
         confidence: high|medium|low|none,
         citations: [{source_type, source_id, filing_id, page_number, similarity}],
         router_reason }
```

- **Citations** point back to the exact `filing_chunks.id` / `filing_tables.id`,
  the filing, and the page.
- **Confidence** (document path) is banded from the chosen chunk's cosine
  similarity, floored so a grounded-but-weak match reads LOW, not overconfident.
  Table hits are HIGH (exact cell). 
- **"Insufficient evidence"** is a first-class, valid outcome: `sufficient=false`,
  `confidence=none`, empty `citations`. Triggered when no retrieved sentence
  shares a content word with the question (grounding check), not just a raw
  similarity threshold — which is what makes the refusal robust.

## Grounding check (why the refusal is reliable)

A pure cosine threshold is a poor refusal gate — bge gives unrelated text
moderate similarity (~0.46 for "CEO's favorite color" here). Instead, an answer
is only emitted if a retrieved sentence actually contains a question content-word
(length ≥ 3, substring-matched as light stemming so "recommend" hits
"recommended"). Off-topic questions share no content word → refusal. This is
tested directly.

## Schema additions

- `filings.ticker` (indexed) — retrieval scope; backfilled by the indexer
  (company = first line of the filing; ticker = slug of its first word).
- `filing_chunks.embedding` / `transcript_segments.embedding` — `vector(384)`,
  nullable, populated by `retrieval.index` (idempotent backfill).

`retrieval/schema.py` adds these via idempotent `ALTER … IF NOT EXISTS` because
the Phase 1 tables already exist and `create_all` won't alter them.

## "Done" checklist (CLAUDE.md)

- [x] Runs end-to-end locally via docker-compose (`retrieval.index` + `POST /qa`).
- [x] Has a test (`tests/test_retrieval.py`, 5 Q&A pairs asserting citations).
- [x] Has this design note.

## Known limitations / next steps

- Transcript segments are embedded (as required) but not yet ticker-scoped, so
  QA targets `filing_chunks`; linking transcripts to a ticker is a small follow-up.
- Router is keyword-only; upgrade path is a zero-shot classifier behind the same
  `route()` seam.
- Extractive answers are single-sentence; the `ClaudeAnswerer` seam is where
  multi-chunk synthesis lands.
- Add an ANN index (ivfflat/hnsw) once the corpus outgrows exact search.
