"""Local filings 'fetcher'.

WHY no scraper: reliably scraping NSE is out of scope for this phase (bot
protection, unstable markup). Instead we treat a local directory of
manually-downloaded (or generated) sample PDFs as the source. This keeps the
same interface a real fetcher would expose — "give me the filings to ingest" —
so a future NSE fetcher can slot in behind ``discover_filings`` without changing
the pipeline.
"""

from __future__ import annotations

from pathlib import Path

from app.config import Settings


def discover_filings(settings: Settings) -> list[Path]:
    """Return the sample PDF filings to ingest, sorted for determinism.

    Returns an empty list (not an error) if the directory is missing or holds
    no PDFs — the CLI decides whether that's fatal.
    """
    filings_dir = Path(settings.filings_dir)
    if not filings_dir.is_dir():
        return []
    return sorted(p for p in filings_dir.glob("*.pdf") if p.is_file())
