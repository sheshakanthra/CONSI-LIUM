# Phase 1 — Ingestion Layer

> Design note for the ingestion phase. Per CLAUDE.md, each phase ships a short
> markdown note capturing the design decisions (resume/interview talking
> points).

## What this phase delivers

A local, end-to-end ingestion layer under `apps/api/ingestion/` that turns
sample inputs into **queryable** Postgres rows — no scraping, no business logic
beyond parse → structure → persist.

```
data/filings/*.pdf ──▶ pdf_parser ──▶ chunking ──▶ filings
                                   └─▶ tables ────▶ filing_chunks
                                                    filing_tables

data/transcripts/*.wav ──▶ asr (faster-whisper) ──▶ transcripts
                                                     transcript_segments
```

Run it:

```bash
docker compose exec api python -m ingestion.generate_samples   # sample PDFs
docker compose exec api python -m ingestion.run all            # ingest all
docker compose exec api pytest tests/test_ingestion.py -v      # integration test
```

## Decisions worth defending

1. **No scraper — a local "fetcher" behind a stable seam.** Reliably scraping
   NSE (bot protection, unstable markup) is out of scope this phase.
   `filings.discover_filings()` reads a directory of sample PDFs but exposes the
   same "give me the filings to ingest" interface a real fetcher would, so an
   NSE fetcher can slot in later without touching the pipeline.

2. **Tables stay structured, never flattened (the core decision).** The PDF
   parser returns page *text* and *tables* as two separate things. Tables are
   persisted to `filing_tables` as `columns` + `rows` JSONB — not merged into
   the chunk text — because Table QA later must address cells ("row 3,
   'Revenue'"), which is impossible once a table is stringified into prose. The
   integration test asserts a known cell (`Revenue`) survives as structured
   data.

3. **`content_hash` (sha256) as an idempotency key.** `filings` and
   `transcripts` carry a UNIQUE hash of the file bytes. Re-running ingestion
   detects duplicates and writes nothing, so the CLI is safe to re-run. A
   dedicated test asserts a second ingest of the same PDF is a no-op.

4. **Character-window, per-page chunking — deliberately dumb.** Chunking runs at
   ingestion time, before we've committed to an embedding model/tokenizer, so it
   stays character-based and overlapping (sentences straddling a boundary
   survive). Each chunk keeps its `page_number` for later citation. Token-aware
   / semantic chunking is a retrieval-phase refinement, not an ingestion
   concern.

5. **Embeddings deferred on purpose.** `filing_chunks` has no vector column yet:
   its dimensionality depends on the embedding model chosen in the retrieval
   phase, and locking it in now would be premature. pgvector is already enabled
   on the database for when it lands.

6. **faster-whisper, tiny/CPU/int8, VAD on.** ASR is locked to faster-whisper
   for local dev (CLAUDE.md). `tiny`/`int8` keeps runs fast and GPU-free; VAD
   filtering avoids hallucinated text over the silences common in call audio.
   Per-segment start/end timestamps are preserved in `transcript_segments`. The
   model + detected language are stored on `transcripts` for reproducibility.

7. **No silent failure.** Every external call (PDF parse, model load, transcribe)
   is wrapped and re-raised as `IngestionError` with the offending file in the
   message; the CLI turns that into a non-zero exit code.

## Schema (SQLAlchemy 2.0, explicit)

| table                 | key columns                                                  |
| --------------------- | ------------------------------------------------------------ |
| `filings`             | `content_hash` UNIQUE, `num_pages`, `file_path`, `source`    |
| `filing_chunks`       | FK→filings, `chunk_index`, `page_number`, `text`, `char_count` · UNIQUE(filing_id, chunk_index) |
| `filing_tables`       | FK→filings, `page_number`, `table_index`, `columns` JSONB, `rows` JSONB · UNIQUE(filing_id, page_number, table_index) |
| `transcripts`         | `content_hash` UNIQUE, `language`, `duration_seconds`, `model_name` |
| `transcript_segments` | FK→transcripts, `segment_index`, `start_seconds`, `end_seconds`, `text` · UNIQUE(transcript_id, segment_index) |

FK deletes cascade at both the ORM (`delete-orphan`) and DB (`ON DELETE
CASCADE`) level.

## Sample data (gitignored)

`data/` is gitignored, so samples are **regenerated**, not committed:

- **PDFs:** `python -m ingestion.generate_samples` (reportlab) writes two
  synthetic filings, each with prose and a financial table.
- **Audio:** `apps/api/ingestion/generate_sample_audio.ps1` uses Windows
  System.Speech (offline TTS) to produce a ~30s spoken earnings-call clip, so
  the ASR path has real speech to transcribe without any cloud dependency.

## Testing notes / gotchas

- The integration test is marked `integration`; it **skips** cleanly if Postgres
  is unreachable, and the audio assertions skip if the sample WAV is absent.
- The module-level async engine binds its asyncpg pool to one event loop. Tests
  run on a single **session-scoped** loop (`pytest.ini`), and the ingestion
  fixture calls `engine.dispose()` first so a prior sync test (the health
  check's `TestClient`) can't leave a stale, wrong-loop pool that would make the
  DB look unreachable.

## "Done" checklist (CLAUDE.md)

- [x] Runs end-to-end locally via docker-compose (`ingestion.run all`).
- [x] Has an integration test (`tests/test_ingestion.py`) asserting rows land.
- [x] Has this design note.

## Deviations surfaced

- Added `requests==2.32.3` to `requirements.txt`: `faster-whisper` 1.0.3 imports
  it but its `huggingface_hub` pin didn't pull it transitively in the slim
  image. Flagged rather than silently worked around.
