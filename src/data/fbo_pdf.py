"""Parse pre-2019-20 Final Budget Outcome PDFs.

Pre-2019-20 FBOs are PDF-only (no DOCX upstream). The aggregates table is on a
single page captioned "Table 1: Australian Government general government sector
budget aggregates". Output schema matches `fbo_docx.load_fbo_outcome` so the
two parsers emit interchangeable rows.

Approach: extract page text, locate the caption line and the `$b $b $b ...` unit
row, then walk each data row identifying the Outcome column from the right (last
column if no Change column in headers, else second-to-last).
"""

from __future__ import annotations

import re

import pandas as pd
import pdfplumber

from src.utilities.paths import OUTCOME_DIR

_TABLE_CAPTION_RE = re.compile(
    r"Table\s+\d+:\s+Australian Government general government sector budget aggregates",
    re.IGNORECASE,
)
_UNIT_ROW_RE = re.compile(r"^\$b(?:\s+\$b)+\s*$")
_FOOTNOTE_START_RE = re.compile(r"^\(\s*[a-z]\s*\)")
_NUMBER_RE = re.compile(r"^-?\d[\d,]*\.?\d*$")
_FOOTNOTE_LABEL_RE = re.compile(r"\s*\([a-z]+(?:,\s*[a-z]+)*\)\s*$")

MEASURE_DOLLARS = "$b"
MEASURE_PCT_GDP = "Per cent of GDP"


def _fbo_pdf_path(year: str):
    return OUTCOME_DIR / year / "fbo.pdf"


def _parse_number(token: str) -> float | None:
    s = (
        token.replace(",", "")
        .replace("\xa0", "")
        .replace("–", "-")  # en-dash
        .replace("—", "-")  # em-dash
        .replace("−", "-")  # unicode minus
    )
    if not s or s in {"-", "..", "na", "n.a."}:
        return None
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    if _NUMBER_RE.match(s):
        try:
            return float(s)
        except ValueError:
            return None
    return None


def _clean_line_item(label: str) -> str:
    return _FOOTNOTE_LABEL_RE.sub("", label.strip().replace("\xa0", " "))


def _find_aggregates_page(pdf: pdfplumber.PDF) -> int:
    for i, page in enumerate(pdf.pages):
        text = page.extract_text() or ""
        if _TABLE_CAPTION_RE.search(text):
            return i
    raise ValueError("Aggregates table caption not found in PDF")


def _parse_data_line(line: str, outcome_col: int) -> tuple[str, float | None] | None:
    """Parse a row like ``Receipts(a) 284.7 303.7 302.0`` into ``(label, outcome_value)``.

    The Outcome value is at left-anchored column index ``outcome_col`` in the row's
    trailing numeric run. If the row is shorter than expected (e.g. a Per cent of
    GDP row drops the Change column at the end), the same left-anchored index
    still points at the Outcome cell.
    """
    if _FOOTNOTE_START_RE.match(line):
        return None
    tokens = line.split()
    if not tokens:
        return None

    # Parse trailing numeric run
    numbers: list[float] = []
    i = len(tokens) - 1
    while i >= 0:
        v = _parse_number(tokens[i])
        if v is None:
            break
        numbers.append(v)
        i -= 1
    numbers.reverse()

    if not numbers:
        return None  # label-only line (e.g. "Memorandum item:")

    label = " ".join(tokens[: i + 1])
    value = numbers[outcome_col] if 0 <= outcome_col < len(numbers) else None
    return (label, value)


def load_fbo_outcome(year: str) -> pd.DataFrame:
    """Extract Outcome column from a pre-2019-20 FBO PDF.

    Returns the same long-format frame as `fbo_docx.load_fbo_outcome`.
    """
    path = _fbo_pdf_path(year)
    if not path.exists():
        raise FileNotFoundError(f"No FBO PDF for {year}: {path}")

    with pdfplumber.open(str(path)) as pdf:
        page_idx = _find_aggregates_page(pdf)
        text = pdf.pages[page_idx].extract_text() or ""

    lines = [line.rstrip() for line in text.split("\n")]

    caption_idx = next(
        i for i, line in enumerate(lines) if _TABLE_CAPTION_RE.search(line)
    )

    # Locate the $b $b ... unit row immediately below the headers
    bb_idx: int | None = None
    for i in range(caption_idx + 1, len(lines)):
        if _UNIT_ROW_RE.match(lines[i].strip()):
            bb_idx = i
            break
    if bb_idx is None:
        raise ValueError(f"Could not find $b unit row after caption (year={year})")

    full_cols = lines[bb_idx].split().count("$b")
    header_text = " ".join(lines[caption_idx + 1 : bb_idx])
    outcome_col = full_cols - 2 if "Change" in header_text else full_cols - 1

    rows: list[dict] = []
    current_item: str | None = None
    for line in lines[bb_idx + 1 :]:
        line = line.strip()
        if not line:
            continue
        if _FOOTNOTE_START_RE.match(line):
            break  # end of table

        parsed = _parse_data_line(line, outcome_col)
        if parsed is None:
            continue
        label, value = parsed
        label = _clean_line_item(label)
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

        if value is None:
            continue
        rows.append({
            "fiscal_year": year,
            "line_item": line_item,
            "measure": measure,
            "value": value,
        })
    return pd.DataFrame(rows)
