"""Parse BP1 Statement 2 economic-outlook forecasts.

Treasury publishes its detailed economic forecasts in Statement 2 of every BP1,
in a table captioned "Domestic economy – detailed forecasts" (or similar
across years). The table has ~20 line items grouped into National Accounts,
Prices and wages, Labour market, and Balance of payments sections.

Quirks worth noting:

- **Treasury fractions**: values use fractional notation (`1 3/4` = 1.75,
  `1/4` = 0.25). Negative fractions can be split across tokens (`- 1/4` →
  -0.25). Same convention as the RBA SOMP.
- **Mixed measures**: most rows are `% change` year-on-year, but Unemployment
  rate / Participation rate are `% level`, Current account balance is
  `% of GDP`, Change in inventories / Net exports are `% pt contribution`,
  Net overseas migration is `persons`.
- **Section headers** (e.g. "By industry", "Prices and wages") are
  label-only rows with no numeric values — those get skipped.
- **Short horizon**: only ~4 fiscal year columns (prior actual + budget
  year + 1-2 forwards), shorter than the fiscal-aggregates table.

Output schema matches the other parquets::

    budget_year   "2024-25"
    fiscal_year   "2024-25"
    line_item     "Real gross domestic product"
    measure       "% change" | "%" | "% of GDP" | "% pt contribution" | "persons"
    value         float
"""

from __future__ import annotations

import re

import fitz
import pandas as pd
import pdfplumber

from src.utilities.paths import BUDGET_DIR

_CAPTION_RE = re.compile(
    r"(domestic economy.*forecasts|detailed forecasts)",
    re.IGNORECASE,
)
_YEAR_RE = re.compile(r"^\d{4}[-–—]\d{2}$")
_INTEGER_RE = re.compile(r"^-?\d+$")
_FRACTION_RE = re.compile(r"^-?\d+/\d+$")
_DECIMAL_RE = re.compile(r"^-?\d[\d,]*\.?\d*$")
_FOOTNOTE_START_RE = re.compile(r"^\(?[a-z]\)\s")
_LABEL_FOOTNOTE_RE = re.compile(r"\s*\([a-z]+\)\s*$")

# Outline matchers for Statement 2 boundaries (PyMuPDF TOC).
_S2_RE = re.compile(r"statement\s+2:|bp1_bst2(?!\d)|BP1_BS2(?!\d)", re.IGNORECASE)
_S3_RE = re.compile(r"statement\s+3:|bp1_bst3(?!\d)|BP1_BS3(?!\d)", re.IGNORECASE)


def _normalize_year(t: str) -> str:
    return t.replace("–", "-").replace("—", "-")


def _parse_year_list(line: str) -> list[str]:
    return [_normalize_year(t) for t in line.split() if _YEAR_RE.match(t)]


def _is_fraction(t: str) -> bool:
    return bool(_FRACTION_RE.match(t))


def _is_integer(t: str) -> bool:
    return bool(_INTEGER_RE.match(t))


def _is_number(t: str) -> bool:
    return bool(_DECIMAL_RE.match(t.replace(",", "")))


def _is_value_token(t: str) -> bool:
    return _is_number(t) or _is_fraction(t) or t == "-"


def _parse_value_tokens(tokens: list[str]) -> list[float]:
    """Convert tokens like ['3.1', '1', '3/4', '2', '2', '1/4'] to [3.1, 1.75, 2.0, 2.25].

    Handles compound fractions ('N M/D'), standalone fractions ('M/D'),
    standalone decimals, comma-grouped numbers ('528,000'), and standalone
    '-' as a negative sign attached to the following value.
    """
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
        # Compound: integer followed by fraction → 'N M/D' (or '-N M/D')
        if _is_integer(t) and i + 1 < len(tokens) and _is_fraction(tokens[i + 1]):
            whole = int(t)
            num, den = tokens[i + 1].split("/")
            frac = int(num) / int(den)
            # For '-3 1/2', whole = -3 → -3.5, not -3 + 0.5 = -2.5.
            combined = (whole - frac) if whole < 0 else (whole + frac)
            values.append(sign * combined)
            i += 2
            continue
        if _is_fraction(t):
            num, den = t.split("/")
            values.append(sign * (int(num) / int(den)))
            i += 1
            continue
        if _is_number(t):
            values.append(sign * float(t.replace(",", "")))
            i += 1
            continue
        # Non-value token — stop
        break
    return values


def _split_label_and_value_tokens(line: str) -> tuple[str, list[str]] | tuple[None, None]:
    """Split a row into (label, value_tokens). Returns (None, None) if the row
    doesn't have a label-then-values shape."""
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


def _determine_measure(label: str) -> str:
    lower = label.lower()
    if "per cent of gdp" in lower:
        return "% of GDP"
    if "per cent" in lower:
        return "%"
    if "overseas migration" in lower:
        return "persons"
    if "change in inventories" in lower or "net exports" in lower:
        return "% pt contribution"
    return "% change"


# Cross-year line-item aliases. Older BP1s (mostly 2010-11 to 2013-14) use
# slightly different names for the same underlying series. Mapping resolves
# them to the modern canonical name so charts can query one line_item across
# all 17 budgets. Keys are lower-cased (matched case-insensitively); values are
# the canonical name to emit. Only TRUE aliases — historically discontinued
# breakdowns (Non-farm product, Total final demand, etc.) are left as-is.
_LINE_ITEM_ALIASES: dict[str, str] = {
    "gross domestic product": "Real gross domestic product",
    "consumer price index": "Consumer price index",
    "wage price index": "Wage price index",
    "employment (labour force survey basis)": "Employment",
    "dwellings": "Dwelling investment",
}


def _clean_line_item(label: str) -> str:
    stripped = _LABEL_FOOTNOTE_RE.sub("", label).strip()
    return _LINE_ITEM_ALIASES.get(stripped.lower(), stripped)


def _find_statement_2_range(pdf_path: str) -> tuple[int | None, int | None]:
    """Return (start_page, end_page) for Statement 2 via PDF outline."""
    doc = fitz.open(pdf_path)
    try:
        toc = doc.get_toc()
    finally:
        doc.close()
    start: int | None = None
    end: int | None = None
    for _lvl, title, pg in toc:
        if start is None and _S2_RE.search(title):
            start = pg
            continue
        if start is not None and _S3_RE.search(title):
            end = pg
            break
    return start, end


def load_bp1_economic(budget_year: str) -> pd.DataFrame:
    """Extract the Statement 2 economic forecasts table for one BP1."""
    path = BUDGET_DIR / budget_year / "bp1.pdf"
    if not path.exists():
        raise FileNotFoundError(f"No BP1 PDF for {budget_year}: {path}")

    start, end = _find_statement_2_range(str(path))

    # If the outline is missing or degenerate (e.g. 2017-18 BP1's outline has
    # every L2 entry pointing to page 5), fall back to scanning a wider window
    # likely to contain Statement 2. Statement 2 typically sits in the first
    # quarter of every BP1.
    rows: list[dict] = []
    with pdfplumber.open(str(path)) as pdf:
        if start is None or (end is not None and end - start < 5):
            scan_start, scan_end = 0, min(len(pdf.pages), 120)
        else:
            scan_start = start - 1
            scan_end = (end - 1) if end else len(pdf.pages)

        target_text: str | None = None
        for page in pdf.pages[scan_start: scan_end]:
            text = page.extract_text() or ""
            # The forecast table caption is specific enough on its own to
            # uniquely identify the right page. Require Unemployment too just
            # to disqualify any narrative page that happens to use the phrase.
            if _CAPTION_RE.search(text) and "Unemployment" in text:
                target_text = text
                break

    if target_text is None:
        return pd.DataFrame()

    lines = target_text.split("\n")
    caption_idx = next(i for i, l in enumerate(lines) if _CAPTION_RE.search(l))

    # Year list line: first line below caption with >= 3 fiscal years
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

    for line in lines[year_list_idx + 1:]:
        s = line.strip()
        if not s:
            continue
        # End of table at footnotes / Source / Note
        if _FOOTNOTE_START_RE.match(s) or s.startswith(("Source:", "Note:")):
            break

        label, value_tokens = _split_label_and_value_tokens(s)
        if label is None:
            continue
        values = _parse_value_tokens(value_tokens)
        if not values:
            continue

        line_item = _clean_line_item(label)
        if not line_item:
            continue
        measure = _determine_measure(label)

        for fy, val in zip(fiscal_years, values):
            rows.append({
                "budget_year": budget_year,
                "fiscal_year": fy,
                "line_item": line_item,
                "measure": measure,
                "value": val,
            })

    return pd.DataFrame(rows)
