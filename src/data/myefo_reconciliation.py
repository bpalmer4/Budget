"""Parse the MYEFO underlying cash balance reconciliation table from the MYEFO PDF.

MYEFO Part 3 reconciles the Budget underlying cash balance to the MYEFO one
("Reconciliation of general government sector underlying cash balance
estimates", Table 3.2 in 2025-26). It runs in stages — "Changes from 2025-26
Budget to 2025 PEFO", then "Changes from 2025 PEFO to 2025-26 MYEFO" (only the
second stage exists outside election years) — and each stage splits the change
into policy decisions and parameter and other variations::

    Changes from 2025 PEFO to
    2025-26 MYEFO
    Effect of policy decisions(a)(b)
    Receipts -151 -103 -819 -511 -1,584
    Payments 1,758 44 -2,156 -3,399 -3,754
    Total policy decisions impact on
    underlying cash balance -1,909 -147 1,337 2,888 2,170
    Effect of parameter and other variations(b)
    ...

A stage may give only the effect on the balance (an "Effect of ..." row with
values), with no Receipts/Payments split; that row is kept with line_item
"Underlying cash balance". Totals and level rows are skipped: they are sums
of the kept rows.

Values are published in $m and converted to $b. Signs are as published: a
positive Payments value is more spending, which *worsens* the balance.

Output schema::

    budget_year   str    "2025-26"   # the Budget this MYEFO revises
    fiscal_year   str    "2026-27"
    stage         str    "2025 PEFO to 2025-26 MYEFO"
    component     str    "Policy decisions" | "Parameter and other variations"
    line_item     str    "Receipts" | "Payments" | "Underlying cash balance"
    measure       str    "$b"
    value         float
"""

from __future__ import annotations

import re

import pandas as pd
import pdfplumber

from src.utilities.paths import MYEFO_DIR

_CAPTION_RE = re.compile(
    r"Reconciliation of general government sector underlying cash balance",
    re.IGNORECASE,
)
_YEAR_RE = re.compile(r"^\d{4}[-–—]\d{2}$")
_NUMBER_RE = re.compile(r"^-?\d[\d,]*$")
_FOOTNOTE_RE = re.compile(r"^\(?[a-z]\)\s")
_LABEL_FOOTNOTE_RE = re.compile(r"(?:\s*\([a-z]\))+\s*$")
_STAGE_RE = re.compile(r"^Changes from\s+(.*)$")
_COMPONENTS: dict[str, str] = {
    "Effect of policy decisions": "Policy decisions",
    "Effect of parameter and other variations": "Parameter and other variations",
}
_SPLIT_ITEMS = ("Receipts", "Payments")
BALANCE_ITEM = "Underlying cash balance"
_HEADER_SEARCH_WINDOW = 6
_MIN_YEARS = 3
_M_PER_B = 1000.0


def _parse_number(token: str) -> float | None:
    s = token.replace(",", "").replace("−", "-").replace("–", "-")
    return float(s) if _NUMBER_RE.match(s) else None


def _split_values(line: str) -> tuple[str, list[float]]:
    """Split a line into its label and its trailing run of numbers."""
    tokens = line.split()
    values: list[float] = []
    while tokens:
        v = _parse_number(tokens[-1])
        if v is None:
            break
        values.append(v)
        tokens.pop()
    values.reverse()
    return _LABEL_FOOTNOTE_RE.sub("", " ".join(tokens)).strip(), values


def _find_years(lines: list[str], caption_idx: int) -> tuple[list[str], int] | None:
    """Return (fiscal years, index of the line after the year row)."""
    for i in range(caption_idx + 1, min(caption_idx + 1 + _HEADER_SEARCH_WINDOW, len(lines))):
        years: list[str] = []
        for token in lines[i].split():
            if not _YEAR_RE.match(token):
                break  # stops at "Total"
            years.append(token.replace("–", "-").replace("—", "-"))
        if len(years) >= _MIN_YEARS:
            return years, i + 1
    return None


def _parse_table(lines: list[str], caption_idx: int, budget_year: str) -> list[dict]:
    found = _find_years(lines, caption_idx)
    if found is None:
        return []
    fiscal_years, data_start = found

    rows: list[dict] = []
    stage: str | None = None
    stage_open = False  # the stage title wraps onto the next line
    component: str | None = None

    def emit(line_item: str, values: list[float]) -> None:
        if stage is None or component is None or len(values) < len(fiscal_years):
            raise ValueError(f"Reconciliation row out of place: {line_item!r} {values}")
        rows.extend(
            {
                "budget_year": budget_year,
                "fiscal_year": fy,
                "stage": stage,
                "component": component,
                "line_item": line_item,
                "measure": "$b",
                "value": v / _M_PER_B,
            }
            for fy, v in zip(fiscal_years, values, strict=False)
        )

    for raw in lines[data_start:]:
        line = raw.strip()
        if not line:
            continue
        if _FOOTNOTE_RE.match(line):
            break
        label, values = _split_values(line)
        stage_match = _STAGE_RE.match(line)
        if stage_match:
            stage, stage_open, component = stage_match.group(1).strip(), True, None
            continue
        if stage_open and not values:
            stage = f"{stage} {label}"
            stage_open = False
            continue
        stage_open = False
        if label in _COMPONENTS:
            component = _COMPONENTS[label]
            if values:  # stage gives only the effect on the balance
                emit(BALANCE_ITEM, values)
            continue
        if label in _SPLIT_ITEMS and values:
            emit(label, values)
    return rows


def load_myefo_reconciliation(budget_year: str) -> pd.DataFrame:
    """Extract the underlying cash balance reconciliation for one MYEFO."""
    path = MYEFO_DIR / budget_year / "myefo.pdf"
    if not path.exists():
        raise FileNotFoundError(f"No MYEFO PDF for {budget_year}: {path}")

    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            if not _CAPTION_RE.search(text):
                continue
            lines = [line.rstrip() for line in text.split("\n")]
            caption_idx = next(i for i, line in enumerate(lines) if _CAPTION_RE.search(line))
            rows = _parse_table(lines, caption_idx, budget_year)
            if rows:
                return pd.DataFrame(rows)
    raise ValueError(f"No underlying cash balance reconciliation parsed from MYEFO {budget_year}")
