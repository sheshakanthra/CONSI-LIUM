"""End-to-end ingestion CLI.

Usage (inside the api container, or on host with DATABASE_URL pointed at the
DB and the sample files present):

    python -m ingestion.run init-db          # create tables
    python -m ingestion.run filings          # ingest every PDF in filings_dir
    python -m ingestion.run audio <path>     # ingest one audio file
    python -m ingestion.run all              # init-db + filings + sample audio

WHY a thin argparse CLI rather than a framework: ingestion is an operational
batch job, not a service surface. Keeping it dependency-light makes it trivial
to run in a container exec or a cron later. All heavy lifting lives in
``pipeline`` so this file only parses args and prints a summary.

Per CLAUDE.md "no silent failure": IngestionError is caught at the top level,
logged with the offending file, and turned into a non-zero exit code.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from app.config import get_settings
from app.db import SessionLocal
from ingestion import pipeline
from ingestion.errors import IngestionError
from ingestion.filings import discover_filings


async def _run_filings() -> int:
    settings = get_settings()
    paths = discover_filings(settings)
    if not paths:
        print(
            f"No PDF filings found in {settings.filings_dir!r}. "
            "Generate samples with:  python -m ingestion.generate_samples",
            file=sys.stderr,
        )
        return 1

    async with SessionLocal() as session:
        for path in paths:
            res = await pipeline.ingest_filing(session, path, settings)
            verb = "ingested" if res.is_new else "skipped (duplicate)"
            print(
                f"[filing] {verb}: {res.file_name} "
                f"(pages={res.num_pages}, chunks={res.num_chunks}, tables={res.num_tables})"
            )
    return 0


async def _run_audio(audio_path: Path) -> int:
    settings = get_settings()
    async with SessionLocal() as session:
        res = await pipeline.ingest_audio(session, audio_path, settings)
        verb = "ingested" if res.is_new else "skipped (duplicate)"
        print(
            f"[audio] {verb}: {res.file_name} "
            f"(lang={res.language}, duration={res.duration_seconds}, "
            f"segments={res.num_segments})"
        )
    return 0


def _default_audio_path() -> Path | None:
    """First audio file in the configured transcripts dir, if any."""
    settings = get_settings()
    transcripts_dir = Path(settings.transcripts_dir)
    if not transcripts_dir.is_dir():
        return None
    for pattern in ("*.wav", "*.mp3", "*.m4a", "*.flac"):
        matches = sorted(transcripts_dir.glob(pattern))
        if matches:
            return matches[0]
    return None


async def _run_all() -> int:
    await pipeline.create_schema()
    code = await _run_filings()

    audio = _default_audio_path()
    if audio is None:
        print(
            f"No audio file found in {get_settings().transcripts_dir!r}; "
            "skipping ASR. (See docs/phase1-ingestion.md to generate one.)",
            file=sys.stderr,
        )
    else:
        code = await _run_audio(audio) or code
    return code


async def _dispatch(args: argparse.Namespace) -> int:
    if args.command == "init-db":
        await pipeline.create_schema()
        print("Schema created (or already present).")
        return 0
    if args.command == "filings":
        await pipeline.create_schema()
        return await _run_filings()
    if args.command == "audio":
        await pipeline.create_schema()
        return await _run_audio(Path(args.path))
    if args.command == "all":
        return await _run_all()
    raise AssertionError(f"unhandled command {args.command!r}")


def main() -> int:
    parser = argparse.ArgumentParser(description="CONSILIUM ingestion CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db", help="create ingestion tables")
    sub.add_parser("filings", help="ingest all PDFs in the filings dir")
    audio_p = sub.add_parser("audio", help="ingest one audio file")
    audio_p.add_argument("path", help="path to an audio file")
    sub.add_parser("all", help="init-db + all filings + sample audio")

    args = parser.parse_args()
    try:
        return asyncio.run(_dispatch(args))
    except IngestionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
