"""Parse the MYEFO budget aggregates tables from the MYEFO PDF.

MYEFO Part 3 carries two aggregates tables, found by caption:

- "Australian Government general government sector budget aggregates"
  (cash: Underlying cash balance, Receipts, Payments, debt, ...)
- "Australian Government general government sector accrual aggregates"
  (Revenue, Expenses, Net operating balance, Fiscal balance, ...)

Unlike BP1, each line item is a label row followed by one sub-row per
publication — MYEFO, then PEFO (election years only), then Budget — and the
columns alternate $b and % GDP for each fiscal year::

    Receipts
    MYEFO  749.8 25.7 777.0 25.8 805.6 25.5 846.9 25.4 26.6
    PEFO   735.4 25.5 ...
    Budget 735.4 25.5 ...

The cash table ends with a medium-term column (e.g. 2035-36) that has % GDP
only; it is dropped. Only the MYEFO sub-rows are kept: the Budget sub-rows
duplicate `bp1_estimates.parquet` (checked identical for 2025-26).

Output schema matches `bp1_estimates.parquet`::

    budget_year   str    "2025-26"   # the Budget this MYEFO revises
    fiscal_year   str    "2026-27"
    line_item     str    "Receipts"
    measure       str    "$b" or "Per cent of GDP"
    value         float
"""

from __future__ import annotations

import re

import pandas as pd
import pdfplumber

from src.utilities.paths import MYEFO_DIR

_CAPTION_RE = re.compile(
    r"Australian Government general government sector\s+(?:budget|accrual)\s+aggregates",
    re.IGNORECASE,
)
_YEAR_RE = re.compile(r"^\d{4}[-–—]\d{2}$")
_NUMBER_RE = re.compile(r"^-?\d[\d,]*\.?\d*$")
_FOOTNOTE_RE = re.compile(r"^\(?[a-z]\)")
_LABEL_FOOTNOTE_RE = re.compile(r"\s*\([a-z]+(?:,\s*[a-z]+)*\)\s*$")
_END_RE = re.compile(r"^(?:Table|Part)\s+\d")  # prose or page footer after the table

_MYEFO_ROW = "MYEFO"
_VERSION_ROWS = ("MYEFO", "PEFO", "Budget")
_DOLLAR_UNIT = "$b"
_HEADER_SEARCH_WINDOW = 6  # year and unit rows sit within this many lines of the caption
_MIN_YEARS = 3

MEASURE_DOLLARS = "$b"
MEASURE_PCT_GDP = "Per cent of GDP"


def _parse_number(token: str) -> float | None:
    s = token.replace(",", "").replace("−", "-").replace("–", "-")
    return float(s) if _NUMBER_RE.match(s) else None


def _find_header(lines: list[str], caption_idx: int) -> tuple[list[str], int, int] | None:
    """Return (fiscal_years, number of $b columns, index of the first data line).

    The year row may list a trailing medium-term year; the unit row tells how
    many years carry a $b column (the rest are % GDP only).
    """
    window = lines[caption_idx + 1 : caption_idx + 1 + _HEADER_SEARCH_WINDOW]
    for offset, line in enumerate(window):
        tokens = line.split()
        years = [t.replace("–", "-").replace("—", "-") for t in tokens if _YEAR_RE.match(t)]
        if len(years) < _MIN_YEARS or len(years) != len(tokens):
            continue
        year_idx = caption_idx + 1 + offset
        unit_idx = year_idx + 1
        if unit_idx >= len(lines):
            return None
        n_dollar = lines[unit_idx].split().count(_DOLLAR_UNIT)
        if n_dollar == 0:
            return None
        return years[:n_dollar], n_dollar, unit_idx + 1
    return None


def _parse_table(lines: list[str], caption_idx: int, budget_year: str) -> list[dict]:
    header = _find_header(lines, caption_idx)
    if header is None:
        return []
    fiscal_years, n_dollar, data_start = header

    rows: list[dict] = []
    line_item: str | None = None
    for raw in lines[data_start:]:
        line = raw.strip()
        if not line:
            continue
        if _FOOTNOTE_RE.match(line) or _END_RE.match(line):
            break
        first, _, rest = line.partition(" ")
        if first not in _VERSION_ROWS:
            line_item = _LABEL_FOOTNOTE_RE.sub("", line).strip()
            continue
        if first != _MYEFO_ROW or line_item is None:
            continue
        values = [_parse_number(t) for t in rest.split()]
        if any(v is None for v in values) or len(values) < 2 * n_dollar:
            raise ValueError(f"Unexpected MYEFO row for {line_item!r}: {line!r}")
        for i, fy in enumerate(fiscal_years):
            for measure, value in ((MEASURE_DOLLARS, values[2 * i]), (MEASURE_PCT_GDP, values[2 * i + 1])):
                if value is None:  # unreachable after the check above; narrows the type
                    continue
                rows.append(
                    {
                        "budget_year": budget_year,
                        "fiscal_year": fy,
                        "line_item": line_item,
                        "measure": measure,
                        "value": value,
                    }
                )
    return rows


def load_myefo_estimates(budget_year: str) -> pd.DataFrame:
    """Extract the MYEFO rows of the cash and accrual aggregates tables for one year."""
    path = MYEFO_DIR / budget_year / "myefo.pdf"
    if not path.exists():
        raise FileNotFoundError(f"No MYEFO PDF for {budget_year}: {path}")

    all_rows: list[dict] = []
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            if not _CAPTION_RE.search(text):
                continue
            lines = [line.rstrip() for line in text.split("\n")]
            caption_idx = next(i for i, line in enumerate(lines) if _CAPTION_RE.search(line))
            all_rows.extend(_parse_table(lines, caption_idx, budget_year))

    if not all_rows:
        raise ValueError(f"No aggregates table parsed from MYEFO {budget_year}")
    df = pd.DataFrame(all_rows)
    return df.drop_duplicates(subset=["budget_year", "fiscal_year", "line_item", "measure"], keep="first").reset_index(
        drop=True
    )
