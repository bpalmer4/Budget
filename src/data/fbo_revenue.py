"""Parse FBO accrual revenue-by-head outcomes.

The FBO Part 1 revenue table lists every head of revenue with the Budget (or
MYEFO) estimate, the outcome and the change:

- **2019-20 onwards (DOCX):** `fbo_01_part_1.docx`, the Word table whose
  first column contains a "Taxation revenue" row (the cash table next to it
  says "Taxation receipts" instead).
- **Pre-2019-20 (PDF only):** `fbo.pdf`, "Table 4: Australian Government
  general government sector (accrual) revenue" ("sector revenue" in 2010-11).
  The Outcome column is second-last, before "Change on ...".

Output schema matches `fbo_outcomes.parquet`:

    fiscal_year   "2025-26"
    line_item     head of revenue, e.g. "Company tax" (incl. "Total revenue")
    measure       "$b"
    value         float   (Treasury's $m / 1000)
"""

from __future__ import annotations

import re

import pandas as pd
import pdfplumber
import pymupdf
from docx import Document
from docx.document import Document as DocxDocument
from docx.table import Table as DocxTable

from src.data.revenue_heads import TOTAL_REVENUE, canonical_head, parse_number, split_text_row
from src.utilities.paths import OUTCOME_DIR

_TAXATION_REVENUE = "Taxation revenue"


def _row(fiscal_year: str, head: str, value_m: float) -> dict:
    return {"fiscal_year": fiscal_year, "line_item": head, "measure": "$b", "value": value_m / 1000.0}


# ---------------------------------------------------------------------------
# DOCX (2019-20 onwards)
# ---------------------------------------------------------------------------


def _docx_revenue_table(doc: DocxDocument) -> DocxTable:
    for tbl in doc.tables:
        labels = [canonical_head(row.cells[0].text) for row in tbl.rows]
        if _TAXATION_REVENUE in labels and TOTAL_REVENUE in labels:
            return tbl
    raise ValueError("No accrual revenue table (with a 'Taxation revenue' row) in FBO Part 1")


def _docx_outcome_column(tbl: DocxTable) -> int:
    """Index of the column whose header rows say 'Outcome' (and not 'Estimate'/'Change')."""
    n_header = next(i for i, row in enumerate(tbl.rows) if row.cells[0].text.strip())
    matches: list[int] = []
    for c in range(len(tbl.columns)):
        header = " ".join(tbl.rows[r].cells[c].text for r in range(n_header))
        if "Outcome" in header and "Estimate" not in header and "Change" not in header:
            matches.append(c)
    if len(matches) != 1:
        raise ValueError(f"Expected one Outcome column, found {matches}")
    return matches[0]


def load_fbo_revenue_docx(fiscal_year: str) -> pd.DataFrame:
    """Extract accrual revenue outcomes by head from FBO Part 1 DOCX."""
    path = OUTCOME_DIR / fiscal_year / "fbo_01_part_1.docx"
    if not path.exists():
        raise FileNotFoundError(f"No FBO Part 1 DOCX for {fiscal_year}: {path}")

    tbl = _docx_revenue_table(Document(str(path)))
    col = _docx_outcome_column(tbl)
    rows: list[dict] = []
    for row in tbl.rows:
        head = canonical_head(row.cells[0].text)
        value = parse_number(row.cells[col].text)
        if head and value is not None:
            rows.append(_row(fiscal_year, head, value))
        if head == TOTAL_REVENUE:
            break
    return pd.DataFrame(rows).drop_duplicates(subset=["fiscal_year", "line_item", "measure"])


# ---------------------------------------------------------------------------
# PDF (pre-2019-20)
# ---------------------------------------------------------------------------

_PDF_CAPTION_RE = re.compile(
    r"Table \d+: Australian Government general government sector (?:\(accrual\) )?revenue",
    re.IGNORECASE,
)
_UNIT_ROW_RE = re.compile(r"^\$m(?:\s+\$m){2,}$")
_MIN_CELLS = 3  # estimate(s), outcome, change
_MAX_TABLE_PAGES = 3


def _pdf_table_pages(path: str) -> list[int]:
    """Pages holding the table: the first caption page through the one with Total revenue.

    Some years (2012-13 to 2014-15) break the table across two pages, with the
    caption repeated as "(continued)" and "Total revenue" only on the second.
    """
    with pymupdf.open(path) as doc:
        for page in doc:
            if not _PDF_CAPTION_RE.search(re.sub(r"\s+", " ", page.get_text())):
                continue
            pages: list[int] = []
            for idx in range(page.number, min(page.number + _MAX_TABLE_PAGES, len(doc))):
                pages.append(idx)
                if TOTAL_REVENUE in doc[idx].get_text():
                    return pages
    raise ValueError("FBO accrual revenue table not found in PDF")


def _pdf_page_rows(text: str, fiscal_year: str) -> tuple[list[dict], bool]:
    """Rows from one page of the table, and whether Total revenue was reached."""
    lines = [line.strip() for line in text.split("\n")]
    unit_idx = next((i for i, line in enumerate(lines) if _UNIT_ROW_RE.match(line)), None)
    if unit_idx is None:
        raise ValueError(f"No $m unit row in {fiscal_year} FBO revenue table page")
    n_cells = lines[unit_idx].split().count("$m")
    header = " ".join(lines[:unit_idx])
    if "Outcome" not in header or "Change" not in header:
        raise ValueError(f"Unexpected {fiscal_year} FBO revenue table header: {header!r}")
    outcome_col = n_cells - 2  # ... | Outcome | Change on ...

    rows: list[dict] = []
    for line in lines[unit_idx + 1:]:
        label, cells = split_text_row(line)
        if len(cells) != n_cells or len(cells) < _MIN_CELLS or not label:
            continue
        head = canonical_head(label)
        value = cells[outcome_col]
        if value is not None:
            rows.append(_row(fiscal_year, head, value))
        if head == TOTAL_REVENUE:
            return rows, True
    return rows, False


def load_fbo_revenue_pdf(fiscal_year: str) -> pd.DataFrame:
    """Extract accrual revenue outcomes by head from the FBO PDF (Part 1, Table 4)."""
    path = OUTCOME_DIR / fiscal_year / "fbo.pdf"
    if not path.exists():
        raise FileNotFoundError(f"No FBO PDF for {fiscal_year}: {path}")

    rows: list[dict] = []
    with pdfplumber.open(str(path)) as pdf:
        for page_idx in _pdf_table_pages(str(path)):
            page_rows, done = _pdf_page_rows(pdf.pages[page_idx].extract_text() or "", fiscal_year)
            rows.extend(page_rows)
            if done:
                break
    return pd.DataFrame(rows).drop_duplicates(subset=["fiscal_year", "line_item", "measure"])
