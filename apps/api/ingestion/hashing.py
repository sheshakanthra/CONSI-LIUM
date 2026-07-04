"""Content hashing for idempotent ingestion.

WHY sha256 of file bytes: it's the idempotency key on ``filings`` and
``transcripts``. Re-ingesting the same file produces the same hash, so the
pipeline can detect "already ingested" and skip, instead of creating duplicate
rows. We stream the file in chunks so hashing a large PDF/audio file doesn't
load it entirely into memory.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

_READ_CHUNK = 1 << 20  # 1 MiB


def sha256_file(path: str | Path) -> str:
    """Return the hex sha256 digest of a file's contents."""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(_READ_CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()
