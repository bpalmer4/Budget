"""Parse BP1's accrual revenue-by-head reconciliation tables.

Every BP1 from 2010-11 onwards carries two tables titled "Reconciliation of
{year} general government (accrual) revenue" in the revenue statement: one for
the year the Budget is delivered in (its estimated outcome) and one for the
budget year. Each has four numeric columns — MYEFO, Budget, change $m,
change % — and this parser takes the **Budget** column.

BP1 publishes accrual revenue by head for these two years only; the
multi-year by-head table covers cash receipts. So each Budget contributes two
points per head.

Emits long-format rows matching `bp1_estimates.parquet`:

    budget_year   "2025-26"
    fiscal_year   "2024-25" or "2025-26"
    line_item     head of revenue, e.g. "Company tax" (incl. "Total revenue")
    measure       "$b"
    value         float   (Treasury's $m / 1000)
"""

from __future__ import annotations

import re

import pandas as pd
import pdfplumber
import pymupdf

from src.data.revenue_heads import TOTAL_REVENUE, canonical_head, split_text_row
from src.utilities.paths import BUDGET_DIR

_CAPTION_RE = re.compile(
    r"Reconciliation of (\d{4}[-–]\d{2}) general government \(accrual\) revenue",
    re.IGNORECASE,
)
_UNIT_ROW_RE = re.compile(r"^\$m\s+\$m\s+\$m\s+%$")
_N_CELLS = 4  # MYEFO, Budget, change $m, change %
_BUDGET_COL = 1


def _find_table_pages(path: str) -> list[tuple[int, str]]:
    """Return (page index, fiscal year) for each accrual reconciliation table.

    PyMuPDF pre-scan for speed. A page qualifies only if it also carries the
    "Total revenue" row, which rules out contents pages and prose mentions.
    """
    found: list[tuple[int, str]] = []
    with pymupdf.open(path) as doc:
        for page in doc:
            text = re.sub(r"\s+", " ", page.get_text())
            m = _CAPTION_RE.search(text)
            if m and TOTAL_REVENUE in text:
                found.append((page.number, m.group(1).replace("–", "-")))
    return found


def _parse_table(page_text: str, budget_year: str, fiscal_year: str) -> list[dict]:
    lines = [line.strip() for line in page_text.split("\n")]
    start = next((i for i, line in enumerate(lines) if _UNIT_ROW_RE.match(line)), None)
    if start is None:
        raise ValueError(f"No '$m $m $m %' unit row in {budget_year} table for {fiscal_year}")

    rows: list[dict] = []
    for line in lines[start + 1:]:
        label, cells = split_text_row(line)
        if len(cells) != _N_CELLS or not label:
            continue  # header rows (no cells) and anything that isn't a table row
        value = cells[_BUDGET_COL]
        head = canonical_head(label)
        if value is not None:
            rows.append({
                "budget_year": budget_year,
                "fiscal_year": fiscal_year,
                "line_item": head,
                "measure": "$b",
                "value": value / 1000.0,
            })
        if head == TOTAL_REVENUE:
            break
    return rows


def load_bp1_revenue(budget_year: str) -> pd.DataFrame:
    """Return every head of accrual revenue from one BP1's two reconciliation tables."""
    path = BUDGET_DIR / budget_year / "bp1.pdf"
    if not path.exists():
        raise FileNotFoundError(f"No BP1 PDF for {budget_year}: {path}")

    pages = _find_table_pages(str(path))
    if not pages:
        raise ValueError(f"No accrual revenue reconciliation tables in {budget_year} BP1")

    rows: list[dict] = []
    with pdfplumber.open(str(path)) as pdf:
        for page_idx, fiscal_year in pages:
            rows.extend(_parse_table(pdf.pages[page_idx].extract_text() or "", budget_year, fiscal_year))
    return pd.DataFrame(rows).drop_duplicates(
        subset=["budget_year", "fiscal_year", "line_item", "measure"]
    ).reset_index(drop=True)
