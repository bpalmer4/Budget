"""Parse BP1's top-level "Estimates of expenses by function" table.

This table sits in Statement 5 / Statement 6 of every BP1 from 2010-11 onwards
and lists the same 14 GFS functions in the same order: General public services,
Defence, Public order and safety, Education, Health, Social security and
welfare, Housing and community amenities, Recreation and culture, Fuel and
energy, Agriculture forestry and fishing, Mining manufacturing and
construction, Transport and communication, Other economic affairs, Other
purposes. Followed by a Total expenses row.

The structure is uniform: caption "Estimates of expenses by function", a year
list of 5 fiscal years (typically Estimate + 4 Projections), a `$m $m $m $m $m`
units row, 14 data rows, a Total row, footnotes.

Output rows match the existing `bp1_estimates.parquet` schema so the existing
plot functions work without code changes:

    budget_year   "2024-25"
    fiscal_year   "2024-25"
    line_item     "Defence"               (the function name)
    measure       "$b"
    value         float                   (Treasury's $m converted to $b)
"""

from __future__ import annotations

import re

import pandas as pd
import pdfplumber

from src.utilities.paths import BUDGET_DIR

_CAPTION_RE = re.compile(r"Estimates of expenses by function(?! and sub)", re.IGNORECASE)
_YEAR_RE = re.compile(r"^\d{4}[-–—]\d{2}$")
_UNIT_ROW_RE = re.compile(r"^\$m(?:\s+\$m)+\s*$")
_NUMBER_RE = re.compile(r"^-?\d[\d,]*\.?\d*$")
_FOOTNOTE_LINE_RE = re.compile(r"^\(?[a-z]\)")
# Match "Total expenses" at the start of a row (the row continues with numeric
# columns). Used as the end-of-table marker.
_TOTAL_RE = re.compile(r"^total\s+expenses\b", re.IGNORECASE)
# Minimum numeric tokens for a line to count as data (vs page footer / prose).
_MIN_VALUE_TOKENS_FOR_DATA = 3
_NA_TOKENS = {"-", "..", "na", "n.a.", "NA"}


def _normalize_year(token: str) -> str:
    return token.replace("–", "-").replace("—", "-")


def _parse_number(token: str) -> float | None:
    s = token.replace(",", "").replace("\xa0", "").replace("–", "-").replace("—", "-").replace("−", "-")
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


def _is_value_cell(token: str) -> bool:
    return token in _NA_TOKENS or _parse_number(token) is not None


def _parse_year_list(line: str) -> list[str]:
    years: list[str] = []
    for token in line.split():
        if _YEAR_RE.match(token):
            years.append(_normalize_year(token))
        else:
            break
    return years


def _find_caption_page(pdf: pdfplumber.PDF) -> int:
    """Find the top-level by-function table page.

    Some BP1s have both a top-level table ("expenses by function") and a more
    granular sub-function table ("expenses by function AND sub-function"). The
    caption regex's negative lookahead `(?! and sub)` ensures we only match the
    top-level. We prefer the page with a Total expenses row to avoid pages
    that mention the table caption only in prose.
    """
    candidates: list[int] = []
    for i, page in enumerate(pdf.pages):
        text = page.extract_text() or ""
        if _CAPTION_RE.search(text):
            candidates.append(i)
            if "Total expenses" in text:
                return i
    if candidates:
        return candidates[0]
    raise ValueError("Top-level by-function expenses table caption not found.")


def _parse_data_line(line: str, n_fiscal: int) -> tuple[str, list[float | None]] | None:
    if _FOOTNOTE_LINE_RE.match(line.strip()):
        return None
    tokens = line.split()
    if not tokens:
        return None
    values: list[float | None] = []
    i = len(tokens) - 1
    while i >= 0 and _is_value_cell(tokens[i]):
        values.append(_parse_number(tokens[i]))
        i -= 1
    values.reverse()
    if not values or all(v is None for v in values):
        return None
    # Filter footer/narrative leaks: real function rows have all n_fiscal
    # numeric tokens. A page footer like 'Statement 6: ... | Page 196' only has
    # one trailing number; a narrative paragraph that happens to end with a
    # number will also fall well short of n_fiscal.
    if len(values) < _MIN_VALUE_TOKENS_FOR_DATA:
        return None
    label = " ".join(tokens[: i + 1])
    selected = list(values[:n_fiscal])
    while len(selected) < n_fiscal:
        selected.append(None)
    return label, selected


def load_bp1_functions(budget_year: str) -> pd.DataFrame:
    """Return the 14 function lines of BP1's by-function table for one budget.

    Values are converted from Treasury's published $m to $b for consistency with
    `bp1_estimates.parquet`. The "Total expenses" row is dropped (it duplicates
    the "Expenses" aggregate already in `bp1_estimates.parquet`).
    """
    path = BUDGET_DIR / budget_year / "bp1.pdf"
    if not path.exists():
        raise FileNotFoundError(f"No BP1 PDF for {budget_year}: {path}")

    with pdfplumber.open(str(path)) as pdf:
        page_idx = _find_caption_page(pdf)
        page_text = pdf.pages[page_idx].extract_text() or ""

    lines = [line.rstrip() for line in page_text.split("\n")]
    caption_idx = next(i for i, line in enumerate(lines) if _CAPTION_RE.search(line))

    # Year list line — within a few lines of the caption
    year_list_idx: int | None = None
    fiscal_years: list[str] = []
    for i in range(caption_idx + 1, min(caption_idx + 6, len(lines))):
        years = _parse_year_list(lines[i])
        if len(years) >= 4:
            year_list_idx = i
            fiscal_years = years
            break
    if year_list_idx is None:
        raise ValueError(f"Could not locate year-list line in {budget_year} function table")

    bb_idx: int | None = None
    for i in range(year_list_idx + 1, min(year_list_idx + 4, len(lines))):
        if _UNIT_ROW_RE.match(lines[i].strip()):
            bb_idx = i
            break
    data_start = (bb_idx + 1) if bb_idx is not None else (year_list_idx + 1)

    n_fiscal = len(fiscal_years)
    rows: list[dict] = []
    for line in lines[data_start:]:
        s = line.strip()
        if not s:
            continue
        if _TOTAL_RE.match(s):
            break  # Total expenses row ends the function list
        if _FOOTNOTE_LINE_RE.match(s):
            break

        parsed = _parse_data_line(s, n_fiscal)
        if parsed is None:
            continue
        label, values = parsed
        label = label.replace("\xa0", " ").strip()
        if not label:
            continue
        for fy, val in zip(fiscal_years, values):
            if val is None:
                continue
            rows.append({
                "budget_year": budget_year,
                "fiscal_year": fy,
                "line_item": label,
                "measure": "$b",
                "value": val / 1000.0,  # $m → $b
            })
    return pd.DataFrame(rows)
