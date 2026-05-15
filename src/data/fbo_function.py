"""Parse FBO function-level expenses outcomes.

The expenses-by-function-and-sub-function table is published in FBO Appendix A:

- **2019-20 onwards (DOCX):** `fbo_05_appendix_a.docx` — Table 0 (47 rows).
- **Pre-2019-20 (PDF only):** `fbo.pdf`, captioned
  "Table A1: Australian Government general government sector expenses by
  function and sub-function".

The table has function-header rows (no values) followed by sub-function rows
(with values) and an explicit "Total {function}" row that captures the function
total. Functions without sub-functions (like Defence) appear as a single row
with values directly. This parser captures the 14 function totals, normalising
both representations to a single line_item per function.

Output schema matches `fbo_outcomes.parquet`:

    fiscal_year   str    "2024-25"
    line_item     str    function name (e.g. "Defence")
    measure       str    "$b"
    value         float  (Treasury's $m / 1000)
"""

from __future__ import annotations

import re

import pandas as pd
import pdfplumber
from docx import Document
from docx.table import Table as DocxTable

from src.utilities.paths import OUTCOME_DIR

# The 14 GFS functions that appear in every BP1 / FBO. Source of truth.
KNOWN_FUNCTIONS: tuple[str, ...] = (
    "General public services",
    "Defence",
    "Public order and safety",
    "Education",
    "Health",
    "Social security and welfare",
    "Housing and community amenities",
    "Recreation and culture",
    "Fuel and energy",
    "Agriculture, forestry and fishing",
    "Mining, manufacturing and construction",
    "Transport and communication",
    "Other economic affairs",
    "Other purposes",
)
_FUNCTIONS_LOWER = {f.lower(): f for f in KNOWN_FUNCTIONS}


def _canonical_function(label: str) -> str | None:
    """If `label` represents a function total (function name itself, or
    "Total {function name}"), return the canonical function name. Else None.

    Handles labels with embedded newlines / collapsed whitespace, and labels
    where the trailing word is truncated (e.g. "Total housing and community"
    is unambiguously "Housing and community amenities").
    """
    s = re.sub(r"\s+", " ", label.replace("\xa0", " ").replace("\n", " ")).strip().rstrip(".")
    sl = s.lower()
    if sl in _FUNCTIONS_LOWER:
        return _FUNCTIONS_LOWER[sl]
    if sl.startswith("total "):
        rest = sl[6:].strip()
        if rest in _FUNCTIONS_LOWER:
            return _FUNCTIONS_LOWER[rest]
        # Unique-prefix fallback for truncated cell text
        prefix_matches = [
            fn for fn_lower, fn in _FUNCTIONS_LOWER.items()
            if fn_lower.startswith(rest)
        ]
        if len(prefix_matches) == 1:
            return prefix_matches[0]
    return None


# ---------------------------------------------------------------------------
# DOCX parser (FBO 2019-20 onwards)
# ---------------------------------------------------------------------------

_NUMBER_RE = re.compile(r"^-?\d[\d,]*\.?\d*$")
_NA_TOKENS = {"-", "..", "na", "n.a.", "NA"}


def _parse_number(text: str) -> float | None:
    s = (
        text.strip()
        .replace(",", "")
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


def _docx_find_function_tables(doc: Document) -> list[DocxTable]:
    """Return all tables in the doc that look like part of the function table.

    Treasury's appendix-A is often split across multiple Word tables when the
    underlying source has a page break in the middle — first half on T0, second
    half on T1. Process them all and concatenate the results.
    """
    matching: list[tuple[DocxTable, int]] = []
    for tbl in doc.tables:
        labels = [row.cells[0].text.strip().replace("\xa0", " ") for row in tbl.rows]
        hits = sum(1 for l in labels if _canonical_function(l) is not None)
        if hits >= 3:
            matching.append((tbl, hits))
    if not matching:
        raise ValueError("No function-table-shaped tables found.")
    return [tbl for tbl, _ in matching]


def _docx_column_headers(tbl: DocxTable, n_header: int) -> list[str]:
    n_cols = len(tbl.columns)
    out: list[str] = []
    for c in range(n_cols):
        parts: list[str] = []
        for r in range(min(n_header, len(tbl.rows))):
            t = tbl.rows[r].cells[c].text.strip().replace("\xa0", " ").replace("\n", " ")
            if t and t not in parts:
                parts.append(t)
        out.append(" ".join(parts))
    return out


def _docx_count_header_rows(tbl: DocxTable, max_header: int = 6) -> int:
    n = 0
    for row in tbl.rows[:max_header]:
        if row.cells[0].text.strip() == "":
            n += 1
        else:
            break
    return n


def _identify_outcome_column(headers: list[str], fiscal_year: str) -> int:
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
        f"Could not uniquely identify Outcome column for {fiscal_year}: "
        f"candidates {[(i, headers[i]) for i in candidates]}"
    )


def load_fbo_function_docx(fiscal_year: str) -> pd.DataFrame:
    """Extract function-level expenses outcomes from FBO appendix A DOCX.

    Iterates every function-table-shaped table in the appendix and
    deduplicates: in some years the appendix has a header table plus a
    continuation table, and the function totals can appear in either.
    """
    path = OUTCOME_DIR / fiscal_year / "fbo_05_appendix_a.docx"
    if not path.exists():
        raise FileNotFoundError(f"No FBO appendix A DOCX for {fiscal_year}: {path}")

    doc = Document(str(path))
    tables = _docx_find_function_tables(doc)

    rows: list[dict] = []
    for tbl in tables:
        n_header = _docx_count_header_rows(tbl)
        headers = _docx_column_headers(tbl, n_header)
        try:
            outcome_col = _identify_outcome_column(headers, fiscal_year)
        except ValueError:
            continue
        # `pending_total_function`: handles the case where a "Total X" row has
        # the label on one Word row and the values on the next (e.g. 2024-25
        # appendix_a T1 R18 'Total housing and community' + R19 'amenities').
        pending_total_function: str | None = None
        for row in tbl.rows[n_header:]:
            label = row.cells[0].text.strip().replace("\xa0", " ")
            canonical = _canonical_function(label)
            value = (_parse_number(row.cells[outcome_col].text)
                     if outcome_col < len(row.cells) else None)
            is_total_label = label.lower().startswith("total ")

            if canonical is not None and value is not None:
                # Function total in a single row.
                rows.append({
                    "fiscal_year": fiscal_year, "line_item": canonical,
                    "measure": "$b", "value": value / 1000.0,
                })
                pending_total_function = None
            elif canonical is not None and value is None and is_total_label:
                # "Total X" label without values — values must be on the next row.
                pending_total_function = canonical
            elif (pending_total_function is not None and value is not None
                  and canonical is None):
                # Continuation row: attribute its value to the pending total.
                rows.append({
                    "fiscal_year": fiscal_year, "line_item": pending_total_function,
                    "measure": "$b", "value": value / 1000.0,
                })
                pending_total_function = None
            else:
                pending_total_function = None  # any other row resets
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    # Prefer the LAST occurrence — for functions with sub-functions, the empty
    # header row gets skipped (value is None) and only the "Total X" row emits.
    # For functions without sub-functions (Defence), only one row exists.
    return df.drop_duplicates(
        subset=["fiscal_year", "line_item", "measure"], keep="last"
    ).reset_index(drop=True)


# ---------------------------------------------------------------------------
# PDF parser (pre-2019-20 FBOs)
# ---------------------------------------------------------------------------

_PDF_CAPTION_RE = re.compile(
    r"general government sector expenses by\s+function and sub-function",
    re.IGNORECASE,
)
_YEAR_RE = re.compile(r"^\d{4}[-–—]\d{2}$")
_UNIT_ROW_RE = re.compile(r"^\$m(?:\s+\$m)+\s*$")
_FOOTNOTE_LINE_RE = re.compile(r"^\(?[a-z]\)")


# Two consecutive $m units in close proximity — a strong signal that this page
# is the real table, not a TOC entry that just mentions the appendix.
_PDF_UNITS_PRESENT_RE = re.compile(r"\$m\s+\$m")


def _pdf_find_function_table_page(pdf: pdfplumber.PDF) -> int:
    """Find the page with the function-table caption AND a real $m unit row.

    Older FBOs (2010-11, 2014-15) have a table-of-contents entry that mentions
    "Australian Government general government sector expenses by function and
    sub-function" (with the page number on the same logical line as the entry
    text). Without the $m check we'd latch onto that TOC page.
    """
    for i, page in enumerate(pdf.pages):
        text = page.extract_text() or ""
        if _PDF_CAPTION_RE.search(text) and _PDF_UNITS_PRESENT_RE.search(text):
            return i
    raise ValueError("FBO appendix A function table caption not found in PDF")


def _normalize_year_token(t: str) -> str:
    return t.replace("–", "-").replace("—", "-")


def _pdf_parse_year_list(line: str) -> list[str]:
    out: list[str] = []
    for tok in line.split():
        if _YEAR_RE.match(tok):
            out.append(_normalize_year_token(tok))
    return out


def load_fbo_function_pdf(fiscal_year: str) -> pd.DataFrame:
    """Extract function-level expenses outcomes from FBO PDF (Appendix A).

    The Treasury caption spans two lines ("...expenses by\nfunction and
    sub-function") so a single-line regex match fails. We anchor on the
    PAGE-level caption match (which sees newlines via re's default `\\s+`),
    then locate the data area via the `$m $m $m ...` unit row.
    """
    path = OUTCOME_DIR / fiscal_year / "fbo.pdf"
    if not path.exists():
        raise FileNotFoundError(f"No FBO PDF for {fiscal_year}: {path}")

    with pdfplumber.open(str(path)) as pdf:
        page_idx = _pdf_find_function_table_page(pdf)
        # The function-table appendix often spans multiple pages — concat them.
        pages_text: list[str] = []
        for i in range(page_idx, min(page_idx + 6, len(pdf.pages))):
            t = pdf.pages[i].extract_text() or ""
            if i > page_idx and "$m" not in t:
                break
            pages_text.append(t)
    text = "\n".join(pages_text)

    lines = [line.rstrip() for line in text.split("\n")]

    # Find the first $m unit row — anchors the table data region.
    bb_idx: int | None = None
    for i, line in enumerate(lines):
        if _UNIT_ROW_RE.match(line.strip()):
            bb_idx = i
            break
    if bb_idx is None:
        raise ValueError(f"Could not find $m unit row in {fiscal_year} FBO function table")

    full_cols = lines[bb_idx].split().count("$m")
    # Header text is whatever sits in the few lines above the $m row.
    header_text = " ".join(lines[max(0, bb_idx - 8): bb_idx])
    # Outcome column: N-2 when a Change column is present (newer FBOs), else N-1.
    outcome_col = full_cols - 2 if "Change" in header_text else full_cols - 1

    rows: list[dict] = []
    # Same pending-label trick as the DOCX parser: a "Total X" label can sit
    # on one PDF line with the values wrapped onto the next line (e.g.
    # 'Total housing and community\namenities 6,572 ...').
    pending_total_function: str | None = None
    for line in lines[bb_idx + 1:]:
        s = line.strip()
        if not s:
            continue
        if _FOOTNOTE_LINE_RE.match(s):
            break
        tokens = s.split()
        numbers: list[float | None] = []
        i = len(tokens) - 1
        while i >= 0 and (_parse_number(tokens[i]) is not None or tokens[i] in _NA_TOKENS):
            numbers.append(_parse_number(tokens[i]))
            i -= 1
        numbers.reverse()

        if not numbers:
            # Label-only line: might be a "Total X" with values on next line
            canonical = _canonical_function(s)
            if canonical is not None and s.lower().startswith("total "):
                pending_total_function = canonical
            else:
                pending_total_function = None
            continue

        label = " ".join(tokens[: i + 1])
        canonical = _canonical_function(label)
        value = numbers[outcome_col] if 0 <= outcome_col < len(numbers) else None

        if canonical is not None and value is not None:
            rows.append({
                "fiscal_year": fiscal_year, "line_item": canonical,
                "measure": "$b", "value": value / 1000.0,
            })
            pending_total_function = None
        elif pending_total_function is not None and value is not None and canonical is None:
            # Continuation of previous "Total X" label.
            rows.append({
                "fiscal_year": fiscal_year, "line_item": pending_total_function,
                "measure": "$b", "value": value / 1000.0,
            })
            pending_total_function = None
        else:
            pending_total_function = None
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.drop_duplicates(
        subset=["fiscal_year", "line_item", "measure"], keep="last"
    ).reset_index(drop=True)
