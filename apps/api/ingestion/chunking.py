"""Character-window chunking of extracted page text.

WHY per-page, character-based, overlapping windows:
- Per-page so each chunk keeps a ``page_number`` for citation later (a filing's
  claim should be traceable to a page).
- Character-based (not token-based) because chunking runs at *ingestion* time,
  before we've committed to an embedding model / tokenizer. Token-aware
  splitting is a retrieval-phase refinement; keeping this dumb-but-deterministic
  avoids coupling ingestion to a model choice.
- Overlapping so a sentence spanning a boundary survives in at least one chunk.

This is intentionally simple. It is not sentence- or semantic-aware; that's a
deliberate deferral, not an oversight.
"""

from __future__ import annotations

from dataclasses import dataclass

from ingestion.pdf_parser import ParsedPage


@dataclass
class TextChunk:
    """A single chunk with its source page and global ordinal."""

    chunk_index: int
    page_number: int
    text: str

    @property
    def char_count(self) -> int:
        return len(self.text)


def chunk_pages(
    pages: list[ParsedPage], *, chunk_size: int, chunk_overlap: int
) -> list[TextChunk]:
    """Split each page's text into overlapping windows.

    Args:
        pages: parsed pages (order preserved).
        chunk_size: max characters per chunk (must be > 0).
        chunk_overlap: characters shared between consecutive chunks
            (must be >= 0 and < chunk_size, else we'd loop forever).

    Returns:
        Chunks with a document-global, gap-free ``chunk_index``.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be > 0")
    if not 0 <= chunk_overlap < chunk_size:
        raise ValueError("chunk_overlap must satisfy 0 <= overlap < chunk_size")

    step = chunk_size - chunk_overlap
    chunks: list[TextChunk] = []
    index = 0

    for page in pages:
        text = page.text.strip()
        if not text:
            continue
        start = 0
        while start < len(text):
            window = text[start : start + chunk_size].strip()
            if window:
                chunks.append(
                    TextChunk(
                        chunk_index=index, page_number=page.page_number, text=window
                    )
                )
                index += 1
            start += step

    return chunks
