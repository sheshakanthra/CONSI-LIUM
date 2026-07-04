"""Ingestion error types.

WHY a dedicated exception: CLAUDE.md forbids silent failure — every external
call (PDF parse, ASR) must fail loudly with context. Wrapping lower-level
library errors in ``IngestionError`` gives callers (the CLI, tests) one type to
catch and a message that names the offending file, instead of a bare
pdfminer/ctranslate2 traceback.
"""

from __future__ import annotations


class IngestionError(RuntimeError):
    """Raised when a source file cannot be ingested."""
