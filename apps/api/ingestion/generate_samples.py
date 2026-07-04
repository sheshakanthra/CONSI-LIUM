"""Generate deterministic synthetic sample filings for local ingestion.

WHY this exists: the real source (NSE) isn't scraped this phase, and the raw
``data/`` dir is gitignored, so a fresh checkout has no filings to ingest.
Rather than commit binary PDFs, we regenerate a couple of realistic-enough
filings — each with prose *and* a financial table — so the pipeline and the
integration test always have structured input. These are clearly synthetic and
stand in for manually-downloaded filings.

Run:  python -m ingestion.generate_samples
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.config import get_settings

# (filename, company, headline paragraph, financial table as list-of-rows).
_SAMPLES: list[tuple[str, str, str, list[list[str]]]] = [
    (
        "sample_filing_01.pdf",
        "Acme Industries Ltd.",
        "Acme Industries Ltd. reported consolidated results for the quarter "
        "ended 30 June 2026. Revenue grew on the back of stronger volumes in "
        "the industrial segment, while margins expanded due to lower input "
        "costs. The board recommended an interim dividend, subject to approval. "
        "This document is a synthetic sample used for pipeline testing and does "
        "not represent a real filing.",
        [
            ["Metric (INR crore)", "Q1 FY27", "Q1 FY26", "YoY %"],
            ["Revenue", "1,245", "1,090", "14.2"],
            ["EBITDA", "312", "255", "22.4"],
            ["Net Profit", "188", "141", "33.3"],
            ["EPS (INR)", "9.40", "7.05", "33.3"],
        ],
    ),
    (
        "sample_filing_02.pdf",
        "Globex Corporation Ltd.",
        "Globex Corporation Ltd. announced its audited annual results for the "
        "financial year ended 31 March 2026. Management highlighted improved "
        "working-capital efficiency and a reduction in net debt. Guidance for "
        "the coming year was maintained. This is a synthetic sample document "
        "generated for testing the ingestion layer.",
        [
            ["Segment", "FY26 Revenue", "FY25 Revenue", "Growth %"],
            ["Cloud Services", "4,120", "3,300", "24.8"],
            ["Hardware", "2,050", "2,180", "-6.0"],
            ["Services", "1,760", "1,540", "14.3"],
            ["Total", "7,930", "7,020", "12.9"],
        ],
    ),
]


def _build_pdf(path: Path, company: str, body: str, table_rows: list[list[str]]) -> None:
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(str(path), pagesize=A4, title=company)
    table = Table(table_rows, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#222222")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f2f2")]),
            ]
        )
    )
    story = [
        Paragraph(company, styles["Title"]),
        Spacer(1, 12),
        Paragraph(body, styles["BodyText"]),
        Spacer(1, 18),
        Paragraph("Key Financials", styles["Heading2"]),
        Spacer(1, 6),
        table,
    ]
    doc.build(story)


def generate_samples(filings_dir: str | Path | None = None) -> list[Path]:
    """Write the sample PDFs into ``filings_dir`` (default: configured dir)."""
    target = Path(filings_dir or get_settings().filings_dir)
    target.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    for file_name, company, body, table_rows in _SAMPLES:
        out = target / file_name
        _build_pdf(out, company, body, table_rows)
        written.append(out)
    return written


if __name__ == "__main__":
    paths = generate_samples()
    for p in paths:
        print(f"wrote {p}")
