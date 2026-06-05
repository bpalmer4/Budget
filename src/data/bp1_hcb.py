"""Parse BP1 PDFs for the Headline cash balance row from the cash flow statement.

BP1s up to 2021-22 include Headline cash balance in the Statement 3 headline
aggregates table, so `bp1_pdf.py` picks it up there. From 2022-23 Treasury
dropped it from that table — it survives only in the general government sector
cash flow statement (Statement 10/11 budgeted financial statements), as the row
"Equals headline cash balance", in $m. That row exists in every BP1 back to
2010-11, so this parser runs uniformly across all years; overlap with
`bp1_estimates.parquet` is deduplicated at chart-load time.

Emits long-format rows matching `bp1_estimates.parquet`:

    budget_year   "2026-27"
    fiscal_year   "2028-29"
    line_item     "Headline cash balance"
    measure       "$b"
    value         float
"""

from __future__ import annotations

import re

import fitz  # PyMuPDF — fast page-text pre-scan
import pandas as pd
import pdfplumber

from src.utilities.paths import BUDGET_DIR

LINE_ITEM = "Headline cash balance"

_YEAR_RE = re.compile(r"^\d{4}[-–—]\d{2}$")
# `$m $m $m ...` (or $b) unit row — require at least 3 markers so narrative
# prose ending in `$m` doesn't false-positive.
_UNIT_ROW_RE = re.compile(r"^(?:.*?\s)?(\$b|\$m)(?:\s+(?:\$b|\$m)){2,}\s*$")
_NUMBER_RE = re.compile(r"^-?\d[\d,]*\.?\d*$")
_NA_TOKENS = {"-", "..", "na", "n.a.", "NA"}
# "Equals headline cash balance" optionally followed by a footnote marker.
_HCB_ROW_RE = re.compile(
    r"^Equals\s+headline\s+cash\s+balance(?:\([a-z]+\))?\s+(.+)$",
    re.IGNORECASE,
)
_MIN_VALUES = 4  # need at least 4 numbers to count as a forecast row


def _normalize_year(t: str) -> str:
    return t.replace("–", "-").replace("—", "-")


def _parse_year_list(line: str) -> list[str]:
    return [_normalize_year(tok) for tok in line.split() if _YEAR_RE.match(tok)]


def _parse_number(token: str) -> float | None:
    s = (
        token.replace(",", "")
        .replace("\xa0", "")
        .replace("–", "-")
        .replace("—", "-")
        .replace("−", "-")
    )
    if not s or s in _NA_TOKENS:
        return None
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    if _NUMBER_RE.match(s):
        try:
            return float(s)
        except ValueError:
            return None
    return None


def load_bp1_hcb(budget_year: str) -> pd.DataFrame:
    """Extract the Headline cash balance row from a BP1 cash flow statement.

    Dedupes on (budget_year, fiscal_year, line_item, measure), keeping the
    first occurrence (the general government sector statement precedes any
    other sector's in every BP1).
    """
    path = BUDGET_DIR / budget_year / "bp1.pdf"
    if not path.exists():
        raise FileNotFoundError(f"No BP1 PDF for {budget_year}: {path}")

    # Fast pre-scan with PyMuPDF to find candidate pages, then re-extract just
    # those with pdfplumber (whose text layout the row parser is written for).
    doc = fitz.open(str(path))
    try:
        candidates = [
            i for i, page in enumerate(doc)
            if "Equals headline cash balance" in page.get_text()
        ]
    finally:
        doc.close()

    rows: list[dict] = []
    with pdfplumber.open(str(path)) as pdf:
        for i in candidates:
            text = pdf.pages[i].extract_text() or ""
            if "...." in text[:200]:  # skip TOC pages
                continue
            lines = text.split("\n")
            # Forward pass: track the most recent year list + unit row on this
            # page; the data row below uses that header. Cash flow statement
            # "(continued)" pages repeat the header, so per-page tracking holds.
            current_header: tuple[list[str], str] | None = None
            pending_years: list[str] | None = None
            for line in lines:
                s = line.strip()

                ylist = _parse_year_list(s)
                if len(ylist) >= 4:
                    pending_years = ylist

                if _UNIT_ROW_RE.match(s):
                    unit = "$b" if "$b" in s else "$m"
                    if pending_years is not None:
                        current_header = (pending_years, unit)
                    continue

                m = _HCB_ROW_RE.match(s)
                if not m or current_header is None:
                    continue
                fiscal_years, unit = current_header

                numbers = [_parse_number(tok) for tok in m.group(1).split()]
                if len([n for n in numbers if n is not None]) < _MIN_VALUES:
                    continue

                for fy, val in zip(fiscal_years, numbers[: len(fiscal_years)]):
                    if val is None:
                        continue
                    rows.append({
                        "budget_year": budget_year,
                        "fiscal_year": fy,
                        "line_item": LINE_ITEM,
                        "measure": "$b",
                        "value": val if unit == "$b" else val / 1000.0,
                    })

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.drop_duplicates(
        subset=["budget_year", "fiscal_year", "line_item", "measure"], keep="first"
    ).reset_index(drop=True)
