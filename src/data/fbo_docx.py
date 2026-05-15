"""Parse Final Budget Outcome (FBO) DOCX files and extract the Outcome column.

The Outcome is the only data unique to the FBO — the comparison columns
(Estimate at Budget/MYEFO/PEFO) are duplicated from documents we parse separately.
So this module captures only the Outcome and emits one tidy long-format row per
(fiscal year × line item × measure).

DOCX coverage: 2019-20 onwards. Pre-2019-20 FBOs are PDF-only and handled in
`fbo_pdf.py` (separate parser, separate toolchain).
"""

from __future__ import annotations

import re

import pandas as pd
from docx import Document
from docx.table import Table as DocxTable

from src.utilities.paths import fbo_part_path

# Row labels that uniquely identify the full GFS aggregates table (Table 1.2 in
# recent FBOs). "Fiscal balance" is the discriminator — it appears in the full
# aggregates but not in the slim summary table (Table 1.1) or the reconciliation
# table (Table 1.8). Older FBOs (2019-20, 2020-21) also contain a slim summary
# table that has "Underlying cash balance" + "Receipts" but lacks "Fiscal balance",
# so a two-label match isn't tight enough.
_REQUIRED_LABELS = ("Underlying cash balance", "Receipts", "Fiscal balance")

# Header rows can span up to ~6 stacked rows (year / source / sub-source / unit / ...).
_NUM_HEADER_ROWS_MAX = 6

MEASURE_DOLLARS = "$b"
MEASURE_PCT_GDP = "Per cent of GDP"


def _label(cell_text: str) -> str:
    """Normalise whitespace in a row label."""
    return cell_text.replace("\xa0", " ").strip()


def _find_aggregates_table(doc: Document) -> DocxTable:
    """Locate the aggregates table by content — robust to year-to-year ordering."""
    for tbl in doc.tables:
        labels = {_label(row.cells[0].text) for row in tbl.rows}
        if all(any(req in label for label in labels) for req in _REQUIRED_LABELS):
            return tbl
    raise ValueError(
        f"Could not locate aggregates table (need labels {_REQUIRED_LABELS!r} "
        f"in some table)."
    )


def _column_headers(tbl: DocxTable, n_header_rows: int) -> list[str]:
    """Flatten the first `n_header_rows` rows of `tbl` into one string per column."""
    n_cols = len(tbl.columns)
    headers: list[str] = []
    for c in range(n_cols):
        parts: list[str] = []
        for r in range(min(n_header_rows, len(tbl.rows))):
            text = _label(tbl.rows[r].cells[c].text).replace("\n", " ")
            if text and text not in parts:
                parts.append(text)
        headers.append(" ".join(parts))
    return headers


def _count_header_rows(tbl: DocxTable) -> int:
    """A row is a header row iff its first cell is empty.

    Holds across every FBO year we've inspected (data rows always start with a label
    like 'Underlying cash balance' or 'Per cent of GDP').
    """
    count = 0
    for row in tbl.rows[:_NUM_HEADER_ROWS_MAX]:
        if _label(row.cells[0].text) == "":
            count += 1
        else:
            break
    return count


def _identify_outcome_column(headers: list[str], fiscal_year: str) -> int:
    """Pick the Outcome column matching this fiscal year.

    Some FBOs (e.g. 2019-20) have multiple Outcome columns — prior-year and
    current-year actuals. Prefer the one whose header text contains this FBO's
    own fiscal year. Fall back to the unique Outcome column if there is only one.
    """
    candidates = [
        i for i, h in enumerate(headers)
        if "Outcome" in h and "Change" not in h and "Estimate" not in h
    ]
    matching = [i for i in candidates if fiscal_year in headers[i]]
    if len(matching) == 1:
        return matching[0]
    if len(candidates) == 1:
        return candidates[0]
    raise ValueError(
        f"Could not uniquely identify Outcome column for {fiscal_year}. "
        f"Candidates: {[(i, headers[i]) for i in candidates]}"
    )


# Numbers may be negative, comma-grouped, parenthesised-negative, or have a unicode minus.
_NUMBER_RE = re.compile(r"^-?\d[\d,]*\.?\d*$")
_FOOTNOTE_RE = re.compile(r"\s*\([a-z]+(?:,\s*[a-z]+)*\)\s*$")


def _parse_value(text: str) -> float | None:
    """Parse a numeric cell. Returns None for empty / non-numeric cells."""
    s = (
        text.strip()
        .replace("\xa0", "")
        .replace(",", "")
        .replace("–", "-")  # en-dash
        .replace("—", "-")  # em-dash
        .replace("−", "-")  # unicode minus
    )
    if not s or s in {"-", "..", "na", "n.a."}:
        return None
    # Parenthesised negatives: "(10.0)" → "-10.0"
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    if _NUMBER_RE.match(s):
        return float(s)
    return None


def _clean_line_item(text: str) -> str:
    """Strip trailing footnote markers like '(a)' from a line item label."""
    return _FOOTNOTE_RE.sub("", _label(text))


def load_fbo_outcome(year: str) -> pd.DataFrame:
    """Extract the Outcome column from the aggregates table in this FBO.

    Returns long-format::

        fiscal_year  line_item                  measure              value
        2024-25      Underlying cash balance    $b                   -10.0
        2024-25      Underlying cash balance    Per cent of GDP      -0.4
        2024-25      Receipts                   $b                   717.0
        ...
    """
    path = fbo_part_path(year, "01_part_1")
    if not path.exists():
        raise FileNotFoundError(f"No FBO Part 1 DOCX for {year}: {path}")

    doc = Document(str(path))
    tbl = _find_aggregates_table(doc)
    n_header = _count_header_rows(tbl)
    headers = _column_headers(tbl, n_header)
    outcome_col = _identify_outcome_column(headers, year)

    rows: list[dict] = []
    current_item: str | None = None
    for row in tbl.rows[n_header:]:
        label = _clean_line_item(row.cells[0].text)
        if not label:
            continue
        value = _parse_value(row.cells[outcome_col].text)
        if label == MEASURE_PCT_GDP:
            if current_item is None:
                continue
            line_item = current_item
            measure = MEASURE_PCT_GDP
        else:
            current_item = label
            line_item = label
            measure = MEASURE_DOLLARS
        if value is None:
            continue
        rows.append({
            "fiscal_year": year,
            "line_item": line_item,
            "measure": measure,
            "value": value,
        })
    return pd.DataFrame(rows)
