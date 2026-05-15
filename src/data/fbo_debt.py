"""Parse FBO Net debt and Gross debt outcomes.

These line items aren't in the GFS aggregates table we parse via `fbo_docx.py` /
`fbo_pdf.py`. They sit in the "slim summary" table (Table 1.1 in recent FBOs)
and the balance-sheet section in older PDFs. Output schema matches
`fbo_outcomes.parquet`:

    fiscal_year   str    "2024-25"
    line_item     str    "Net debt" | "Gross debt"
    measure       str    "$b"
    value         float

Gross debt appears in 2022-23 onwards (Treasury added it as a headline aggregate
following the COVID debt accumulation). Net debt appears in all 15 FBO years.
"""

from __future__ import annotations

import re

import pandas as pd
import pdfplumber
from docx import Document
from docx.table import Table as DocxTable

from src.utilities.paths import OUTCOME_DIR

_DEBT_LABEL_RE = re.compile(r"^(Gross|Net)\s+debt(\s*\([a-z]+\))?\s*$", re.IGNORECASE)
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


def _canonical_debt_label(label: str) -> str | None:
    """Returns 'Gross debt' or 'Net debt' (stripped of footnote) or None."""
    m = _DEBT_LABEL_RE.match(label.strip())
    if not m:
        return None
    return f"{m.group(1).capitalize()} debt"


# ---- DOCX ----

def _docx_count_header_rows(tbl: DocxTable, max_header: int = 6) -> int:
    n = 0
    for row in tbl.rows[:max_header]:
        if row.cells[0].text.strip() == "":
            n += 1
        else:
            break
    return n


def _docx_column_headers(tbl: DocxTable, n_header: int) -> list[str]:
    out: list[str] = []
    for c in range(len(tbl.columns)):
        parts: list[str] = []
        for r in range(min(n_header, len(tbl.rows))):
            t = tbl.rows[r].cells[c].text.strip().replace("\xa0", " ").replace("\n", " ")
            if t and t not in parts:
                parts.append(t)
        out.append(" ".join(parts))
    return out


def _identify_outcome_column(headers: list[str], fiscal_year: str) -> int | None:
    candidates = [
        i for i, h in enumerate(headers)
        if "Outcome" in h and "Change" not in h and "Estimate" not in h
    ]
    matching = [i for i in candidates if fiscal_year in headers[i]]
    if len(matching) == 1:
        return matching[0]
    if len(candidates) == 1:
        return candidates[0]
    return None


def load_fbo_debt_docx(fiscal_year: str) -> pd.DataFrame:
    """Extract Net/Gross debt outcomes from the FBO Part 1 DOCX (any table that
    contains them, deduplicated to the latest reading)."""
    path = OUTCOME_DIR / fiscal_year / "fbo_01_part_1.docx"
    if not path.exists():
        raise FileNotFoundError(f"No FBO Part 1 DOCX for {fiscal_year}: {path}")

    doc = Document(str(path))
    rows: list[dict] = []
    for tbl in doc.tables:
        n_header = _docx_count_header_rows(tbl)
        headers = _docx_column_headers(tbl, n_header)
        outcome_col = _identify_outcome_column(headers, fiscal_year)
        if outcome_col is None:
            continue
        for row in tbl.rows[n_header:]:
            label = row.cells[0].text.strip().replace("\xa0", " ")
            canonical = _canonical_debt_label(label)
            if canonical is None:
                continue
            value = _parse_number(row.cells[outcome_col].text)
            if value is None:
                continue
            rows.append({
                "fiscal_year": fiscal_year,
                "line_item": canonical,
                "measure": "$b",
                "value": value,
            })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.drop_duplicates(
        subset=["fiscal_year", "line_item", "measure"], keep="first"
    ).reset_index(drop=True)


# ---- PDF ----

_PDF_UNIT_ROW_RE = re.compile(r"^(\$b|\$m)(?:\s+(\$b|\$m))+\s*$")


def load_fbo_debt_pdf(fiscal_year: str) -> pd.DataFrame:
    """Extract Net/Gross debt outcomes from a pre-2019-20 FBO PDF.

    Older FBOs publish debt levels in the balance-sheet section of Part 1 (or
    Part 2) rather than the headline aggregates table. We scan every page for
    rows matching `<Net|Gross> debt(?)<numbers>` and pick the column matching
    the FBO's own fiscal year. The unit (last $b vs $m row on the same page)
    is inferred to handle mixed reporting (older years often use $m).
    """
    path = OUTCOME_DIR / fiscal_year / "fbo.pdf"
    if not path.exists():
        raise FileNotFoundError(f"No FBO PDF for {fiscal_year}: {path}")

    found: dict[str, float] = {}
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            lines = text.split("\n")
            # Identify the unit row for this page (last one observed before each debt row)
            last_unit_row: str | None = None
            last_header: str = ""
            for line in lines:
                stripped = line.strip()
                if "..." in stripped:
                    continue  # skip TOC entries
                if _PDF_UNIT_ROW_RE.match(stripped):
                    last_unit_row = stripped
                    continue
                # Collect a rolling small header context so we can spot a "Change" column.
                if last_unit_row is None and stripped:
                    last_header = (last_header + " " + stripped)[-200:]
                # Match either "Net debt" / "Gross debt" (newer format) or
                # "Government securities" (older format, = Gross debt as face value
                # of CGS/AGS on issue).
                m = re.match(r"^(Net|Gross)\s+debt(?:\s*\([a-z]+\))?\s+(.+)$", stripped)
                m_govsec = re.match(r"^Government\s+securities(?:\s*\([a-z]+\))?\s+(.+)$", stripped)
                if m_govsec and not m and last_unit_row is not None:
                    debt_label = "Gross debt"
                    m = re.match(r"^()(.+)$", "_ " + m_govsec.group(1))
                    # Construct a pseudo-match so the rest of the code can keep using `m`.
                    class _M:
                        def __init__(self, label_kind: str, tail: str):
                            self._label_kind = label_kind
                            self._tail = tail
                        def group(self, n: int) -> str:
                            return self._tail if n == 2 else self._label_kind
                    m = _M("Gross", m_govsec.group(1))
                if not m or last_unit_row is None:
                    continue
                # If `m` came from the "Net debt"/"Gross debt" regex, use it; else the
                # pseudo-match above already encodes the label.
                debt_label = (
                    f"{m.group(1).capitalize()} debt"
                    if hasattr(m, "re")  # real re.Match has .re attribute
                    else f"{m.group(1).capitalize()} debt"
                )
                # Parse trailing numeric run
                tokens = m.group(2).split()
                numbers: list[float | None] = []
                i = len(tokens) - 1
                while i >= 0 and (_parse_number(tokens[i]) is not None or tokens[i] in _NA_TOKENS):
                    numbers.append(_parse_number(tokens[i]))
                    i -= 1
                numbers.reverse()
                if not numbers:
                    continue
                # Outcome column: -2 if a Change column is in the header, else -1.
                outcome_col = (len(numbers) - 2) if "Change" in last_header else (len(numbers) - 1)
                if outcome_col < 0 or outcome_col >= len(numbers):
                    continue
                value = numbers[outcome_col]
                if value is None:
                    continue
                unit_count_b = last_unit_row.count("$b")
                unit_count_m = last_unit_row.count("$m")
                # If the row's number-count matches the $b units count, it's $b; else $m.
                if unit_count_b == len(numbers):
                    in_billions = value
                elif unit_count_m == len(numbers):
                    in_billions = value / 1000.0
                else:
                    # Ambiguous — assume $m (older format uses millions in detail tables)
                    in_billions = value / 1000.0 if value > 5000 else value
                # Prefer the first occurrence (headline section comes before detail)
                found.setdefault(debt_label, in_billions)

    rows = [
        {"fiscal_year": fiscal_year, "line_item": k, "measure": "$b", "value": v}
        for k, v in found.items()
    ]
    return pd.DataFrame(rows)
