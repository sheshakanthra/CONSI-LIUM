"""CONSILIUM ingestion layer (Phase 1).

Turns local sample inputs — PDF filings and an earnings-call audio clip — into
queryable rows in Postgres:

    filings ─┬─ filing_chunks   (overlapping text windows, for retrieval)
             └─ filing_tables   (structured rows, kept queryable for Table QA)

    transcripts ── transcript_segments  (timestamped ASR output)

Scraping NSE is deliberately out of scope this phase; `filings.py` reads
manually-provided (or generated) sample PDFs from the configured filings dir.
"""
