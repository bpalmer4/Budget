"""Parse Budget Paper No. 1 PDFs and extract the GFS aggregates forward-estimates table.

The same GFS aggregates table appears in every BP1 (Statement 3 in most years),
captioned "Australian Government general government sector budget aggregates".
Each row is a line item (Receipts, Payments, Underlying cash balance, ...) and
each column is a fiscal year: prior actual + in-progress estimate + budget year +
3 forward projections (sometimes + Total + medium-term projection, both of which
we drop).

Older BP1s (2010-11 to 2013-14) use a slightly different format where the `$b`
unit is appended to each line item label rather than appearing as a separate
units row. The parser detects this by the absence of a `$b $b $b ...` line below
the year-list line.

Output schema (long format)::

    budget_year   str    "2014-15"
    fiscal_year   str    "2017-18"  # which year the value refers to
    line_item     str    "Underlying cash balance"
    measure       str    "$b" or "Per cent of GDP"
    value         float
"""

from __future__ import annotations

import re

import pandas as pd
import pdfplumber

from src.utilities.paths import BUDGET_DIR

# Caption identifies an aggregates table. Allows variants:
#   * "Australian Government general government sector budget aggregates" (combined or cash-side)
#   * "Australian Government general government sector budget aggregate"  (pdfplumber drops trailing 's' in 2023-24)
#   * "Australian Government general government sector accrual aggregates" (accrual side, 2023-24 onwards)
# Each BP1 may contain MORE THAN ONE matching page (combined + accrual split,
# or slim Statement 1 summary + full Statement 3 table) — every match is parsed
# and results are deduplicated downstream. The slim "Budget aggregates" table in
# Statement 1 lacks the "Australian Government..." prefix and is filtered out
# by this regex.
_CAPTION_RE = re.compile(
    r"Australian Government general government sector\s+(?:\w+\s+)?aggregates?",
    re.IGNORECASE,
)
# Year tokens may use ASCII hyphen, en-dash, or em-dash depending on the PDF.
# 2023-24 in particular uses en-dashes throughout. Normalised to '-' in output.
_YEAR_RE = re.compile(r"^\d{4}[-–—]\d{2}$")


def _normalize_year(token: str) -> str:
    return token.replace("–", "-").replace("—", "-")
_UNIT_ROW_RE = re.compile(r"^\$b(?:\s+\$b)+\s*$")
_NUMBER_RE = re.compile(r"^-?\d[\d,]*\.?\d*$")
_FOOTNOTE_LINE_RE = re.compile(r"^\([a-z]")
_FOOTNOTE_LABEL_RE = re.compile(r"\s*\([a-z]+(?:,\s*[a-z]+)*\)\s*$")
_DOLLAR_UNIT_SUFFIX_RE = re.compile(r"\s*\(\$b\)\s*$")
# pdfplumber occasionally splits a capitalised first letter from the rest of a
# word ("G ross debt", "R eceipts"). Collapse those.
_SPLIT_CAP_RE = re.compile(r"\b([A-Z])\s+([a-z])")

MEASURE_DOLLARS = "$b"
MEASURE_PCT_GDP = "Per cent of GDP"


_NA_TOKENS = {"-", "..", "na", "n.a.", "n/a", "NA"}


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


def _is_value_cell(token: str) -> bool:
    """True if `token` looks like a value cell (a number or an 'na' placeholder),
    as opposed to a label word. Used to decide where the trailing numeric run
    ends and the row label begins.
    """
    return token in _NA_TOKENS or _parse_number(token) is not None


def _clean_line_item(label: str) -> str:
    """Strip the '($b)' unit suffix (older format), '(a)' footnote markers, and
    re-join split-capital words like 'G ross' → 'Gross'."""
    s = label.strip().replace("\xa0", " ")
    # Apply the strip operations in a small loop because the unit and footnote
    # suffixes can appear in either order (e.g. ' ($b)(a)' or '(a) ($b)').
    for _ in range(3):
        new = _FOOTNOTE_LABEL_RE.sub("", s)
        new = _DOLLAR_UNIT_SUFFIX_RE.sub("", new)
        if new == s:
            break
        s = new
    s = _SPLIT_CAP_RE.sub(r"\1\2", s)
    return s.strip()


def _parse_year_list(line: str) -> list[str]:
    """Return the leading run of YYYY-YY tokens. Stops at the first non-match
    (e.g. ``Total(a)``) so medium-term columns after Total aren't captured."""
    years: list[str] = []
    for token in line.split():
        if _YEAR_RE.match(token):
            years.append(_normalize_year(token))
        else:
            break
    return years


def _split_label_and_values(line: str) -> tuple[str, list[float | None]] | None:
    """Split a row into (label_text, trailing_values).

    `label_text` may be empty if the line is all numbers (a values-only
    continuation row, e.g. 2015-16 where the UCB label appears on one line and
    values on the next). `trailing_values` may be empty if the line is all
    label text (e.g. a `Memorandum item:` standalone label, or a label that
    will be followed by its values on the next line).

    Returns None for empty / footnote lines.
    """
    s = line.strip()
    if not s or _FOOTNOTE_LINE_RE.match(s):
        return None
    tokens = s.split()
    if not tokens:
        return None

    values: list[float | None] = []
    i = len(tokens) - 1
    while i >= 0 and _is_value_cell(tokens[i]):
        values.append(_parse_number(tokens[i]))  # None for 'na' tokens
        i -= 1
    values.reverse()

    label = " ".join(tokens[: i + 1])
    return label, values


# Minimum numeric tokens for a row to count as real data (vs page footer).
_MIN_VALUE_TOKENS_FOR_DATA = 3
# Year list must appear within this many lines below the caption; otherwise
# the caption is likely prose, not a real table heading.
_YEAR_LIST_SEARCH_WINDOW = 6


def _find_caption_pages(pdf: pdfplumber.PDF) -> list[int]:
    """Return every page whose text contains an aggregates-table caption."""
    return [
        i for i, page in enumerate(pdf.pages)
        if _CAPTION_RE.search(page.extract_text() or "")
    ]


def _parse_aggregates_page(page_text: str, budget_year: str) -> list[dict]:
    """Parse one aggregates table from a page's extracted text.

    Returns a list of long-format row dicts. Returns [] if the page doesn't
    actually have a parseable aggregates table (e.g. caption appears in
    paragraph prose, not as a real table caption).
    """
    lines = [line.rstrip() for line in page_text.split("\n")]
    try:
        caption_idx = next(i for i, line in enumerate(lines) if _CAPTION_RE.search(line))
    except StopIteration:
        return []

    # Year list line — must be within a small window below the caption so we
    # don't latch onto narrative prose pages that just *mention* the caption.
    year_list_idx: int | None = None
    fiscal_years: list[str] = []
    for i in range(caption_idx + 1,
                   min(caption_idx + 1 + _YEAR_LIST_SEARCH_WINDOW, len(lines))):
        years = _parse_year_list(lines[i])
        if len(years) >= 4:
            year_list_idx = i
            fiscal_years = years
            break
    if year_list_idx is None:
        return []

    # Optional $b unit row marks end of headers
    bb_idx: int | None = None
    for i in range(year_list_idx + 1, min(year_list_idx + 4, len(lines))):
        if _UNIT_ROW_RE.match(lines[i].strip()):
            bb_idx = i
            break
    data_start = (bb_idx + 1) if bb_idx is not None else (year_list_idx + 1)

    n_fiscal = len(fiscal_years)
    rows: list[dict] = []
    current_item: str | None = None
    pending_label: str | None = None  # label on a line whose values are on the next line

    for line in lines[data_start:]:
        s = line.strip()
        if not s:
            continue
        if _FOOTNOTE_LINE_RE.match(s):
            break

        parsed = _split_label_and_values(s)
        if parsed is None:
            continue
        raw_label, values = parsed
        n_value_tokens = len(values)

        # Case A: label-only line — buffer the label for the next line
        if n_value_tokens == 0:
            pending_label = _clean_line_item(raw_label) if raw_label else None
            continue

        # Case B: values-only line — pair with previously-buffered label
        if not raw_label:
            if pending_label is None:
                continue
            label = pending_label
            pending_label = None
        else:
            label = _clean_line_item(raw_label)
            pending_label = None

        # Filter rows that don't look like real data (e.g. page footers
        # 'Statement 3: ... | Page 57' contribute just one numeric token).
        if n_value_tokens < _MIN_VALUE_TOKENS_FOR_DATA:
            continue
        if not label:
            continue

        if label == MEASURE_PCT_GDP:
            if current_item is None:
                continue
            line_item = current_item
            measure = MEASURE_PCT_GDP
        else:
            current_item = label
            line_item = label
            measure = MEASURE_DOLLARS

        selected = values[:n_fiscal]
        for fy, val in zip(fiscal_years, selected):
            if val is None:
                continue
            rows.append({
                "budget_year": budget_year,
                "fiscal_year": fy,
                "line_item": line_item,
                "measure": measure,
                "value": val,
            })
    return rows


def load_bp1_estimates(budget_year: str) -> pd.DataFrame:
    """Extract BP1 GFS aggregates table(s) for one budget year.

    May parse multiple tables per BP1 (e.g. the 2022-23+ BP1s split aggregates
    into separate "budget aggregates" cash table and "accrual aggregates"
    table). Rows are deduplicated on (budget_year, fiscal_year, line_item,
    measure), keeping the first match.
    """
    path = BUDGET_DIR / budget_year / "bp1.pdf"
    if not path.exists():
        raise FileNotFoundError(f"No BP1 PDF for {budget_year}: {path}")

    with pdfplumber.open(str(path)) as pdf:
        page_indices = _find_caption_pages(pdf)
        page_texts = [pdf.pages[i].extract_text() or "" for i in page_indices]

    if not page_indices:
        raise ValueError(f"No aggregates table caption found in BP1 {budget_year}")

    all_rows: list[dict] = []
    for text in page_texts:
        all_rows.extend(_parse_aggregates_page(text, budget_year))

    df = pd.DataFrame(all_rows)
    if df.empty:
        return df
    return df.drop_duplicates(
        subset=["budget_year", "fiscal_year", "line_item", "measure"], keep="first"
    ).reset_index(drop=True)
