"""Parse FBO Part 2 DOCX files for the Headline cash balance outcome.

FBOs up to 2020-21 include Headline cash balance in the Part 1 aggregates
table, so `fbo_docx.py` picks it up there. From 2021-22 it dropped out of that
table — it survives in the Part 2 cash flow statement as the row
"Equals headline cash balance" (in $m), alongside an Outcome column matching
the FBO's fiscal year. Pre-2019-20 FBOs are PDF-only and already covered by
`fbo_pdf.py`, so this parser handles DOCX years only.

Emits long-format rows matching `fbo_outcomes.parquet`:

    fiscal_year   "2024-25"
    line_item     "Headline cash balance"
    measure       "$b"
    value         float
"""

from __future__ import annotations

import pandas as pd
from docx import Document
from docx.table import Table as DocxTable

from src.data.fbo_docx import (
    _column_headers,
    _count_header_rows,
    _identify_outcome_column,
    _label,
    _parse_value,
)
from src.utilities.paths import fbo_part_path

LINE_ITEM = "Headline cash balance"

_ROW_LABEL = "Equals headline cash balance"


def _find_cash_flow_table(doc: Document) -> DocxTable:
    """Locate the cash flow statement by its distinctive closing row."""
    for tbl in doc.tables:
        if any(_label(row.cells[0].text).startswith(_ROW_LABEL) for row in tbl.rows):
            return tbl
    raise ValueError(
        f"Could not locate cash flow statement (no row starting {_ROW_LABEL!r})."
    )


def load_fbo_hcb(year: str) -> pd.DataFrame:
    """Extract the Headline cash balance outcome from this FBO's Part 2."""
    path = fbo_part_path(year, "02_part_2")
    if not path.exists():
        raise FileNotFoundError(f"No FBO Part 2 DOCX for {year}: {path}")

    doc = Document(str(path))
    tbl = _find_cash_flow_table(doc)
    n_header = _count_header_rows(tbl)
    headers = _column_headers(tbl, n_header)
    outcome_col = _identify_outcome_column(headers, year)

    # The cash flow statement is published in $m; tolerate a future switch to $b.
    divisor = 1.0 if "$b" in headers[outcome_col] else 1000.0

    for row in tbl.rows[n_header:]:
        if not _label(row.cells[0].text).startswith(_ROW_LABEL):
            continue
        value = _parse_value(row.cells[outcome_col].text)
        if value is None:
            continue
        return pd.DataFrame([{
            "fiscal_year": year,
            "line_item": LINE_ITEM,
            "measure": "$b",
            "value": value / divisor,
        }])
    return pd.DataFrame()
