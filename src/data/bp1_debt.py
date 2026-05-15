"""Parse BP1 PDFs for Net debt and Gross debt forecast rows from any table.

Older BP1s (pre-2020-21) don't include Gross/Net debt in the Statement 3
headline aggregates table — so `bp1_pdf.py` doesn't pick them up. But every BP1
since 2010-11 publishes a Net debt forecast row in a balance-sheet-summary
table (typically "Net worth, net financial worth, net debt and net interest
payments"), and BP1s from 2014-15 onwards publish a Gross debt forecast row
as "Face value - end of year" in a CGS/AGS-on-issue table.

This parser scans every page of every BP1 for those two row patterns,
identifies the fiscal-year columns from the table header above each match,
and emits long-format rows matching `bp1_estimates.parquet`:

    budget_year   "2014-15"
    fiscal_year   "2017-18"
    line_item     "Net debt" | "Gross debt"
    measure       "$b"
    value         float
"""

from __future__ import annotations

import re

import fitz  # PyMuPDF — fast outline navigation
import pandas as pd
import pdfplumber

from src.utilities.paths import BUDGET_DIR

# Two-pass outline matcher:
#   1. Newer BP1s (2014-15+) have descriptive bookmarks like
#      "Statement 6: Debt Statement" — match those by requiring an explicit
#      "Statement N:" prefix to avoid Statement 3 sub-headings that talk
#      about the balance sheet in narrative form.
#   2. Older BP1s (2010-11 to 2013-14) only have raw-filename bookmarks
#      like "bp1_bst9" or "BP1_BS9_web". Match those for Statements 6-10.
_STATEMENT_DEBT_RE = re.compile(
    r"statement\s+\d+\s*:.*\b(debt|asset.{0,5}liab|financial\s+statement)",
    re.IGNORECASE,
)
# Negative lookahead `(?!\d)` ensures we match BS6 in "BP1_BS6_part1" without
# matching BS60. \b alone fails because `_` counts as a word char.
_OLD_BOOKMARK_RE = re.compile(
    r"bp1_bst([6-9]|10)(?!\d)|BP1_BS([6-9]|10)(?!\d)", re.IGNORECASE,
)


def _find_debt_section_start(pdf_path: str) -> int:
    """Return the 1-indexed first page of the section likely to contain debt
    tables, using the PDF's outline. Falls back to 1 (scan whole document)
    if the outline has no useful entry.
    """
    doc = fitz.open(pdf_path)
    try:
        toc = doc.get_toc()
    finally:
        doc.close()
    # Pass 1: explicit "Statement N: Debt..." or "Statement N: ...Financial Statements"
    for _level, title, page in toc:
        if _STATEMENT_DEBT_RE.search(title):
            return max(1, page)
    # Pass 2: older raw-filename bookmarks
    for _level, title, page in toc:
        if _OLD_BOOKMARK_RE.search(title):
            return max(1, page)
    return 1

_YEAR_RE = re.compile(r"^\d{4}[-–—]\d{2}$")
# Match a `$m $m $m ...` (or $b) unit row, optionally preceded by a label
# column header like "Note" (older BP1 balance sheets have a Note reference
# column between the label and the values). Require at least 3 unit markers
# so we don't false-positive on narrative prose ending with `$m`.
_UNIT_ROW_RE = re.compile(r"^(?:.*?\s)?(\$b|\$m)(?:\s+(?:\$b|\$m)){2,}\s*$")
_NUMBER_RE = re.compile(r"^-?\d[\d,]*\.?\d*$")
_NA_TOKENS = {"-", "..", "na", "n.a.", "NA"}

# Match either "Net debt" / "Net debt(b)" (Net debt forecast row),
# "Face value - end of year" (Gross debt from CGS/AGS-on-issue tables in
# 2014-15+ BP1s), or "Government securities" (Gross debt from balance-sheet
# liability rows — the only source available in 2010-11 to 2013-14 BP1s).
_DEBT_LABEL_RE = re.compile(
    r"^(Net\s+debt(?:\([a-z]+\))?"
    r"|Face\s+value\s*[-–]\s*end\s+of\s+year"
    r"|Government\s+securities(?:\s*\([a-z]+\))?)\s+(.+)$",
    re.IGNORECASE,
)
# Below this value, a "Government securities" row is almost certainly the
# Public Non-Financial Corporations sub-sector copy of the balance sheet
# (values ~$10b vs general government ~$200b+). drop_duplicates(keep="first")
# already picks the general-government row in practice, but this guard makes
# the intent explicit.
_MIN_GROSS_DEBT_BILLIONS = 50.0
_MIN_VALUES = 4  # need at least 4 trailing numbers to count as a forecast row


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


def _identify_line_item(label_part: str) -> str:
    """Return 'Net debt' or 'Gross debt' based on a matched label fragment."""
    if "net debt" in label_part.lower():
        return "Net debt"
    return "Gross debt"  # "Face value - end of year"


def _find_header_above_with_state(
    lines: list[str], anchor_idx: int, current_header: tuple[list[str], str] | None,
) -> tuple[list[str], str] | None:
    """Return the most recent unit row + year list at or above `anchor_idx`.

    `current_header` is the header found while iterating earlier on the same
    page; we use it if no closer header exists. Balance-sheet tables in older
    BP1s span 30-50 lines, so a tight backward search misses the unit row.
    """
    return current_header


def load_bp1_debt(budget_year: str) -> pd.DataFrame:
    """Extract Net debt and Gross debt forecasts from a BP1 PDF.

    Dedupes on (budget_year, fiscal_year, line_item, measure) — keeps first
    occurrence (typically the baseline-scenario table, which is earlier in the
    document than any sensitivity-scenario variants).
    """
    path = BUDGET_DIR / budget_year / "bp1.pdf"
    if not path.exists():
        raise FileNotFoundError(f"No BP1 PDF for {budget_year}: {path}")

    # Use the PDF outline to jump to the section that contains debt tables —
    # all debt info is in Statement 6+ across every year. Skips the first ~half
    # of each PDF (overview / economy / fiscal strategy / revenue / expenses).
    start_page = _find_debt_section_start(str(path))

    rows: list[dict] = []
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages[start_page - 1:]:
            text = page.extract_text() or ""
            if "...." in text[:200]:  # skip TOC pages
                continue
            lines = text.split("\n")
            # Single forward pass: track the most recent unit row + year list
            # seen on this page; data rows below use that header.
            current_header: tuple[list[str], str] | None = None
            pending_years: list[str] | None = None
            for j, line in enumerate(lines):
                s = line.strip()

                # Track potential year-list lines
                ylist = _parse_year_list(s)
                if len(ylist) >= 4:
                    pending_years = ylist

                # Track unit rows; pair with the most recent year list
                if _UNIT_ROW_RE.match(s):
                    unit = "$b" if "$b" in s else "$m"
                    if pending_years is not None:
                        current_header = (pending_years, unit)
                    continue

                m = _DEBT_LABEL_RE.match(s)
                if not m:
                    continue
                line_item = _identify_line_item(m.group(1))

                # Parse trailing numeric run
                tokens = m.group(2).split()
                numbers: list[float | None] = []
                i_t = len(tokens) - 1
                while i_t >= 0 and (_parse_number(tokens[i_t]) is not None
                                    or tokens[i_t] in _NA_TOKENS):
                    numbers.append(_parse_number(tokens[i_t]))
                    i_t -= 1
                numbers.reverse()
                if len([n for n in numbers if n is not None]) < _MIN_VALUES:
                    continue

                if current_header is None:
                    continue
                fiscal_years, unit = current_header

                # Match the first N values to the N fiscal years (extras = footnotes/totals)
                row_values: list[tuple[str, float]] = []
                for fy, val in zip(fiscal_years, numbers[: len(fiscal_years)]):
                    if val is None:
                        continue
                    value_b = val if unit == "$b" else val / 1000.0
                    row_values.append((fy, value_b))

                # Guard against the PNFC sub-sector "Government securities" row
                # (its values are an order of magnitude smaller). Only checked
                # when the source label was "Government securities" — face-value
                # / Net-debt rows aren't ambiguous in the same way.
                if (line_item == "Gross debt"
                        and "Government securities" in m.group(1).strip()
                        and row_values
                        and max(v for _, v in row_values) < _MIN_GROSS_DEBT_BILLIONS):
                    continue

                for fy, value_b in row_values:
                    rows.append({
                        "budget_year": budget_year,
                        "fiscal_year": fy,
                        "line_item": line_item,
                        "measure": "$b",
                        "value": value_b,
                    })

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.drop_duplicates(
        subset=["budget_year", "fiscal_year", "line_item", "measure"], keep="first"
    ).reset_index(drop=True)
