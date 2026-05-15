"""Parse BP1 Statement 1 (Overview) Table 1.1: Major Economic Parameters from PDF.

PDF path. Used for the 13 budgets where `bp1_bs-1.docx` is not available
(2010-11 → 2021-22 except 2022-23, plus 2023-24).

Layout across years:

- Caption: "Table N: Major economic parameters(a)" — table numbers vary
  ("Table 1" in 2010-11, "Table 2" in 2014-15/2019-20, "Table 1.2" in 2021-22),
  but the phrase "Major economic parameters" is consistent.
- Category row: "Forecasts Projections" / "Outcomes Forecasts Projections" /
  "Outcome Forecasts" — varies; ignored.
- Year row: 5–6 fiscal years (e.g. "2019-20 2020-21 … 2024-25").
- Data rows: label + values. Treasury fractions are split across tokens
  (e.g. `Real GDP 2 3 1/4 4 3 3` parses to [2.0, 3.25, 4.0, 3.0, 3.0]).
- Footnotes start "(a)", then "Source:".

Output schema matches `bp1_overview_docx.py`.
"""

from __future__ import annotations

import re

import fitz
import pandas as pd
import pdfplumber

from src.utilities.paths import BUDGET_DIR

_CAPTION_RE = re.compile(r"major economic parameters", re.IGNORECASE)
_YEAR_RE = re.compile(r"^\d{4}[-–—]\d{2}$")
_INTEGER_RE = re.compile(r"^-?\d+$")
_FRACTION_RE = re.compile(r"^-?\d+/\d+$")
_DECIMAL_RE = re.compile(r"^-?\d[\d,]*\.?\d*$")
_FOOTNOTE_START_RE = re.compile(r"^\(?[a-z]\)\s")

# Outline matchers for the Statement 1 → Statement 2 boundary.
_S1_RE = re.compile(r"statement\s+1:|bp1_bst1(?!\d)|BP1_BS1(?!\d)", re.IGNORECASE)
_S2_RE = re.compile(r"statement\s+2:|bp1_bst2(?!\d)|BP1_BS2(?!\d)", re.IGNORECASE)

# Same canonical names as the DOCX parser so the two paths produce identical
# output for chart-side joins against bp1_economic.parquet.
_LINE_ITEM_ALIASES: dict[str, str] = {
    "real gdp": "Real gross domestic product",
    "nominal gdp": "Nominal gross domestic product",
    "consumer price index": "Consumer price index",
    "cpi": "Consumer price index",
    "wage price index": "Wage price index",
    "employment": "Employment",
    "unemployment rate": "Unemployment rate (per cent)",
}

# The 6 series Table 1.1 covers. Used as a sanity filter on row labels: any
# row whose label doesn't normalise to one of these is skipped (e.g. stray
# narrative lines if pdfplumber concatenates text oddly).
_KNOWN_LABELS = set(_LINE_ITEM_ALIASES.keys())


def _normalize_year(token: str) -> str:
    return token.replace("–", "-").replace("—", "-")


def _parse_year_list(line: str) -> list[str]:
    return [_normalize_year(t) for t in line.split() if _YEAR_RE.match(t)]


def _is_value_token(t: str) -> bool:
    if t == "-":
        return True
    if _FRACTION_RE.match(t) or _INTEGER_RE.match(t):
        return True
    return bool(_DECIMAL_RE.match(t.replace(",", "")))


def _parse_value_tokens(tokens: list[str]) -> list[float]:
    """Convert tokens like ['2', '3', '1/4', '4', '3', '3'] to
    [2.0, 3.25, 4.0, 3.0, 3.0]. Mirrors `bp1_economic.py._parse_value_tokens`."""
    values: list[float] = []
    i = 0
    while i < len(tokens):
        t = tokens[i]
        sign = 1
        if t == "-":
            sign = -1
            i += 1
            if i >= len(tokens):
                break
            t = tokens[i]
        if _INTEGER_RE.match(t) and i + 1 < len(tokens) and _FRACTION_RE.match(tokens[i + 1]):
            whole = int(t)
            num, den = tokens[i + 1].split("/")
            frac = int(num) / int(den)
            combined = (whole - frac) if whole < 0 else (whole + frac)
            values.append(sign * combined)
            i += 2
            continue
        if _FRACTION_RE.match(t):
            num, den = t.split("/")
            values.append(sign * (int(num) / int(den)))
            i += 1
            continue
        if _DECIMAL_RE.match(t.replace(",", "")):
            values.append(sign * float(t.replace(",", "")))
            i += 1
            continue
        break
    return values


def _split_label_and_values(line: str) -> tuple[str, list[str]] | tuple[None, None]:
    tokens = line.strip().split()
    if not tokens:
        return None, None
    start = None
    for i, t in enumerate(tokens):
        if _is_value_token(t):
            start = i
            break
    if start is None or start == 0:
        return None, None
    return " ".join(tokens[:start]), tokens[start:]


def _determine_measure(line_item: str) -> str:
    if "Unemployment rate" in line_item:
        return "%"
    return "% change"


def _find_statement_1_range(pdf_path: str) -> tuple[int | None, int | None]:
    """Return (start_page, end_page_exclusive) for Statement 1 via PDF outline."""
    doc = fitz.open(pdf_path)
    try:
        toc = doc.get_toc()
    finally:
        doc.close()
    start: int | None = None
    end: int | None = None
    for _lvl, title, pg in toc:
        if start is None and _S1_RE.search(title):
            start = pg
            continue
        if start is not None and _S2_RE.search(title):
            end = pg
            break
    return start, end


def load_bp1_overview(budget_year: str) -> pd.DataFrame:
    """Extract Table 1.1 from `bp1.pdf` for one BP1 (PDF path)."""
    path = BUDGET_DIR / budget_year / "bp1.pdf"
    if not path.exists():
        raise FileNotFoundError(f"No bp1.pdf for {budget_year}: {path}")

    start, end = _find_statement_1_range(str(path))

    target_text: str | None = None
    with pdfplumber.open(str(path)) as pdf:
        # Fall back to a wider scan when the outline is missing OR degenerate
        # (some BP1s — notably 2017-18 — have every L2 entry pointing at the
        # same page, so the Statement 1 → Statement 2 range collapses to zero).
        # Statement 1 always lives in the first ~30 pages.
        if start is None or (end is not None and end - start < 3):
            scan_start, scan_end = 0, min(len(pdf.pages), 40)
        else:
            scan_start = start - 1
            scan_end = (end - 1) if end else min(len(pdf.pages), start + 30)

        for page in pdf.pages[scan_start: scan_end]:
            text = page.extract_text() or ""
            if _CAPTION_RE.search(text) and "Real GDP" in text:
                target_text = text
                break

    if target_text is None:
        return pd.DataFrame()

    lines = target_text.split("\n")
    caption_idx = next(
        (i for i, l in enumerate(lines) if _CAPTION_RE.search(l)),
        None,
    )
    if caption_idx is None:
        return pd.DataFrame()

    # Year row: first line below the caption that lists >= 3 fiscal years.
    year_list_idx: int | None = None
    fiscal_years: list[str] = []
    for i in range(caption_idx + 1, min(caption_idx + 6, len(lines))):
        ylist = _parse_year_list(lines[i])
        if len(ylist) >= 3:
            year_list_idx = i
            fiscal_years = ylist
            break
    if year_list_idx is None:
        return pd.DataFrame()

    rows: list[dict] = []
    for line in lines[year_list_idx + 1:]:
        s = line.strip()
        if not s:
            continue
        if _FOOTNOTE_START_RE.match(s) or s.startswith(("Source:", "Note:")):
            break

        label, value_tokens = _split_label_and_values(s)
        if label is None:
            continue
        if label.lower() not in _KNOWN_LABELS:
            continue

        values = _parse_value_tokens(value_tokens)
        if not values:
            continue

        line_item = _LINE_ITEM_ALIASES[label.lower()]
        measure = _determine_measure(line_item)

        for fy, val in zip(fiscal_years, values):
            rows.append({
                "budget_year": budget_year,
                "fiscal_year": fy,
                "line_item": line_item,
                "measure": measure,
                "value": val,
            })

    return pd.DataFrame(rows)
