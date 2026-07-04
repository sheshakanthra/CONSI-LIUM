"""PDF parsing: extract page text AND structured tables *separately*.

WHY pdfplumber: it exposes both ``page.extract_text()`` and
``page.extract_tables()`` over the same layout model, so we can pull prose and
tabular data from one pass without a second tool.

WHY keep them separate (the key decision): a table flattened into a text blob
loses its row/column structure and becomes un-queryable. Downstream Table QA
needs to address cells ("row 3, 'Revenue'"), so tables are returned as
structured rows here and stored as JSONB later — never merged into the chunk
text. Page text and tables are returned side by side; we do not attempt to
subtract table regions from the text (pdfplumber's text extraction may still
include table cells), because the structured ``tables`` list is the canonical,
queryable representation regardless.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber  

from ingestion.errors import IngestionError


@dataclass
class ParsedPage:
    """Extracted text for one page (1-based ``page_number``)."""

    page_number: int
    text: str


@dataclass
class ParsedTable:
    """A structured table located at (page_number, table_index)."""

    page_number: int
    table_index: int
    columns: list[str | None]
    rows: list[list[str | None]]

    @property
    def n_rows(self) -> int:
        return len(self.rows)

    @property
    def n_cols(self) -> int:
        return len(self.columns)


@dataclass
class ParsedPdf:
    """The full parse result for one PDF."""

    num_pages: int
    pages: list[ParsedPage] = field(default_factory=list)
    tables: list[ParsedTable] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        """All page text joined, for callers that want the whole document."""
        return "\n\n".join(p.text for p in self.pages if p.text)


def parse_pdf(path: str | Path) -> ParsedPdf:
    """Parse a PDF into page text and structured tables.

    Raises:
        IngestionError: if the file is missing or cannot be opened/parsed.
    """
    pdf_path = Path(path)
    if not pdf_path.is_file():
        raise IngestionError(f"PDF not found: {pdf_path}")

    pages: list[ParsedPage] = []
    tables: list[ParsedTable] = []

    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            num_pages = len(pdf.pages)
            for page_number, page in enumerate(pdf.pages, start=1):
                pages.append(
                    ParsedPage(page_number=page_number, text=page.extract_text() or "")
                )

                for table_index, raw in enumerate(page.extract_tables()):
                    if not raw:
                        continue
                    # First row is treated as the header (best effort); the rest
                    # are data rows. Cells may be None where pdfplumber found an
                    # empty cell — we preserve that rather than coercing to "".
                    header = raw[0]
                    body = raw[1:] if len(raw) > 1 else []
                    tables.append(
                        ParsedTable(
                            page_number=page_number,
                            table_index=table_index,
                            columns=list(header),
                            rows=[list(r) for r in body],
                        )
                    )
    except IngestionError:
        raise
    except Exception as exc:  # noqa: BLE001 — wrap with file context, don't swallow.
        raise IngestionError(f"Failed to parse PDF {pdf_path}: {exc}") from exc

    return ParsedPdf(num_pages=num_pages, pages=pages, tables=tables)
