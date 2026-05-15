"""Parse BP1 Statement 1 (Overview) Table 1.1: Major Economic Parameters from DOCX.

DOCX path. Used for the 4 budgets with reliable BP1 DOCX (2022-23, 2024-25,
2025-26, 2026-27). Other budgets fall back to `bp1_overview_pdf.py`.

The Overview table extends Treasury's forecast horizon further than the
Statement 2 detailed-forecasts table (Table 2.2) — typically 1 outcome + 5
forecast years vs. 1 outcome + 3 forecasts in S2. Coverage is limited to 6
line items (Real GDP, Employment, Unemployment rate, CPI, WPI, Nominal GDP).

Output schema matches `bp1_economic.parquet`::

    budget_year   "2026-27"
    fiscal_year   "2025-26"
    line_item     "Real gross domestic product"
    measure       "% change" | "%"
    value         float
"""

from __future__ import annotations

import re

import pandas as pd
from docx import Document
from docx.table import Table as DocxTable

from src.utilities.paths import BUDGET_DIR

# Discriminating row labels for Table 1.1. Both must be present.
_REQUIRED_LABELS = ("Real GDP", "Nominal GDP")

_YEAR_CELL_RE = re.compile(r"^\d{4}[-–—]\d{2}$")
_INTEGER_RE = re.compile(r"^-?\d+$")
_FRACTION_RE = re.compile(r"^-?\d+/\d+$")
_DECIMAL_RE = re.compile(r"^-?\d[\d,]*\.?\d*$")

# Canonical line-item names that match `bp1_economic.parquet` so charts can
# join cleanly across both sources.
_LINE_ITEM_ALIASES: dict[str, str] = {
    "real gdp": "Real gross domestic product",
    "nominal gdp": "Nominal gross domestic product",
    "consumer price index": "Consumer price index",
    "cpi": "Consumer price index",
    "wage price index": "Wage price index",
    "employment": "Employment",
    "unemployment rate": "Unemployment rate (per cent)",
}


def _label(text: str) -> str:
    """Normalise whitespace in a cell."""
    return text.replace("\xa0", " ").strip()


def _normalise_year(text: str) -> str:
    return _label(text).replace("–", "-").replace("—", "-")


def _find_overview_table(doc: Document) -> DocxTable:
    """Locate Table 1.1 by required row labels."""
    for tbl in doc.tables:
        labels = {_label(row.cells[0].text) for row in tbl.rows}
        if all(req in labels for req in _REQUIRED_LABELS):
            return tbl
    raise ValueError(
        f"Could not locate Table 1.1 (need row labels {_REQUIRED_LABELS!r})."
    )


def _parse_cell_value(text: str) -> float | None:
    """Parse a Treasury value cell. Handles fractions ('1 3/4', '1/4'),
    decimals ('1.3'), comma-grouped numbers, and unicode minus signs.
    Returns None for empty / non-numeric cells."""
    s = (
        _label(text)
        .replace("–", "-")
        .replace("—", "-")
        .replace("−", "-")
    )
    if not s or s in {"-", "..", "na", "n.a."}:
        return None
    tokens = s.split()
    if not tokens:
        return None

    sign = 1
    i = 0
    if tokens[0] == "-":
        sign = -1
        i = 1
    if i >= len(tokens):
        return None
    t = tokens[i]

    # Compound 'N M/D'
    if _INTEGER_RE.match(t) and i + 1 < len(tokens) and _FRACTION_RE.match(tokens[i + 1]):
        whole = int(t)
        num, den = tokens[i + 1].split("/")
        frac = int(num) / int(den)
        # For '-3 1/2': whole=-3 → -3.5 (subtract), not -2.5 (add).
        combined = (whole - frac) if whole < 0 else (whole + frac)
        return sign * combined
    if _FRACTION_RE.match(t):
        num, den = t.split("/")
        return sign * (int(num) / int(den))
    if _DECIMAL_RE.match(t.replace(",", "")):
        return sign * float(t.replace(",", ""))
    return None


def _determine_measure(canonical_line_item: str) -> str:
    """Unemployment rate is a level; everything else is a % change."""
    if "Unemployment rate" in canonical_line_item:
        return "%"
    return "% change"


def _identify_year_row(tbl: DocxTable) -> int:
    """Return the row index that contains the fiscal-year column headers.

    Across all 4 BP1 DOCX years (2022-23 → 2026-27), the year row is row 1
    (row 0 is the Outcome/Forecasts category labels). Verified rather than
    hardcoded.
    """
    for r in range(min(4, len(tbl.rows))):
        year_cells = sum(
            1 for c in range(1, len(tbl.columns))
            if _YEAR_CELL_RE.match(_normalise_year(tbl.rows[r].cells[c].text))
        )
        if year_cells >= 3:
            return r
    raise ValueError("Could not identify the fiscal-year header row in Table 1.1.")


def load_bp1_overview(budget_year: str) -> pd.DataFrame:
    """Extract Table 1.1 from `bp1_bs-1.docx` for one BP1 (DOCX path)."""
    path = BUDGET_DIR / budget_year / "bp1_bs-1.docx"
    if not path.exists():
        raise FileNotFoundError(f"No bp1_bs-1.docx for {budget_year}: {path}")

    doc = Document(str(path))
    tbl = _find_overview_table(doc)
    year_row = _identify_year_row(tbl)

    # Map column index → fiscal_year string for every column that contains a year.
    fy_columns: list[tuple[int, str]] = []
    for c in range(1, len(tbl.columns)):
        fy = _normalise_year(tbl.rows[year_row].cells[c].text)
        if _YEAR_CELL_RE.match(fy):
            fy_columns.append((c, fy))

    if not fy_columns:
        return pd.DataFrame()

    rows: list[dict] = []
    for r in range(year_row + 1, len(tbl.rows)):
        label = _label(tbl.rows[r].cells[0].text)
        if not label:
            continue
        line_item = _LINE_ITEM_ALIASES.get(label.lower(), label)
        measure = _determine_measure(line_item)
        for c, fy in fy_columns:
            val = _parse_cell_value(tbl.rows[r].cells[c].text)
            if val is None:
                continue
            rows.append({
                "budget_year": budget_year,
                "fiscal_year": fy,
                "line_item": line_item,
                "measure": measure,
                "value": val,
            })

    return pd.DataFrame(rows)
