"""Parse the BP3 'Net overseas migration' table from the Parameters appendix.

Every BP3 since 2010-11 publishes a small NOM table in Appendix A (or B in
2011-12). The table caption is one of::

    Table A.2: Net overseas migration                              # 2010-11 → 2018-19
    Table B.2: Net overseas migration                              # 2011-12
    Table A.2: Net overseas migration                              # 2019-20
    Table A.5: Net overseas migration, for years ending 30 June    # 2020-21 onwards

Two column-label formats exist:

- **Pre-2020-21**: end-year only, e.g. ``2015 2016 2017 2018 2019``.
  Column "YYYY" means the fiscal year ending Jun YYYY, i.e. FY (YYYY-1)-YY.
- **2020-21 onwards**: full FY labels, e.g. ``2020-21 2021-22 …``. Used as-is.

Values are integers (thousands of persons) with optional comma thousand
separators and optional negative signs (COVID border closures produced
negative NOM in 2020-21). Some year columns carry footnote markers like
``2020-21(a)`` which are stripped before parsing.

Output schema matches the other BP3-like sources::

    budget_year   "2024-25"
    fiscal_year   "2024-25"
    line_item     "Net overseas migration"
    measure       "persons"
    value         float
"""

from __future__ import annotations

import re

import fitz
import pandas as pd

from src.utilities.paths import BUDGET_DIR


_CAPTION_RE = re.compile(
    r"Table\s+[A-Z]\.\d+:?\s*Net overseas migration",
    re.IGNORECASE,
)
_LABEL_RE = re.compile(r"^net overseas migration,\s*australia", re.IGNORECASE | re.MULTILINE)
_TOC_LINE_RE = re.compile(r"\.{5,}\s*\d+\s*$")

# Year tokens come in two shapes, both possibly followed by a footnote marker
# like "(a)" with optional surrounding whitespace.
_FY_TOKEN_RE = re.compile(r"^(20\d{2})[-–](\d{2})(?:\s*\([a-z]\))?$")
_YEAR_TOKEN_RE = re.compile(r"^(20\d{2})(?:\s*\([a-z]\))?$")

_VALUE_RE = re.compile(r"^-?\d{1,3}(?:,\d{3})*(?:\.\d+)?$")


def _normalise_fy(token: str) -> str | None:
    """Map a column-header token to fiscal_year 'YYYY-YY'.

    - ``"2020-21"`` → ``"2020-21"``
    - ``"2015"``    → ``"2014-15"`` (year ending Jun 2015 = FY 2014-15)
    - Returns None if the token doesn't look like a year column.
    """
    s = token.strip().replace("–", "-")
    m = _FY_TOKEN_RE.match(s)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    m = _YEAR_TOKEN_RE.match(s)
    if m:
        end = int(m.group(1))
        return f"{end - 1}-{str(end)[-2:]}"
    return None


def _find_table_page(doc: fitz.Document) -> tuple[int, str] | None:
    """Find the BP3 page containing the NOM data table.

    Skips TOC pages (lots of dot-leader lines) and only returns a page where
    the caption appears AND the data row label "Net overseas migration,
    Australia" is also present nearby.
    """
    for i, page in enumerate(doc):
        text = page.get_text() or ""
        if not _CAPTION_RE.search(text):
            continue
        toc_lines = sum(1 for ln in text.split("\n") if _TOC_LINE_RE.search(ln))
        if toc_lines >= 5:
            continue
        if not _LABEL_RE.search(text):
            # Caption present but no data row — might be a section intro page;
            # skip and keep looking.
            continue
        return i, text
    return None


def _parse_table(text: str) -> list[tuple[str, float]]:
    """Given the page text, extract (fiscal_year, value) pairs from the
    NOM table.

    Algorithm:
      1. Locate the caption line.
      2. Walk forward, collecting year tokens until the "Net overseas
         migration, Australia" label.
      3. After the label, collect value tokens (one per FY column).
      4. Pair them up.
    """
    lines = text.split("\n")
    caption_idx = next(
        (i for i, ln in enumerate(lines) if _CAPTION_RE.search(ln)),
        None,
    )
    if caption_idx is None:
        return []

    fy_list: list[str] = []
    label_idx: int | None = None
    for i in range(caption_idx + 1, len(lines)):
        s = lines[i].strip()
        if not s:
            continue
        if _LABEL_RE.match(s):
            label_idx = i
            break
        # A line may contain multiple year tokens separated by whitespace
        # (e.g. "2020-21(a) 2021-22(b)" from 2022-23 BP3).
        for tok in s.split():
            fy = _normalise_fy(tok)
            if fy is not None:
                fy_list.append(fy)

    if label_idx is None or not fy_list:
        return []

    values: list[float] = []
    for i in range(label_idx + 1, len(lines)):
        s = lines[i].strip()
        if not s:
            continue
        # Stop at the next section heading or table — anything that isn't a
        # value token.
        if _VALUE_RE.match(s):
            values.append(float(s.replace(",", "")))
            if len(values) >= len(fy_list):
                break
        else:
            break

    return list(zip(fy_list, values))


def load_bp3_nom(budget_year: str) -> pd.DataFrame:
    """Extract the BP3 Appendix-A NOM table for one budget year.

    Returns an empty DataFrame if the table can't be found or parsed.
    """
    path = BUDGET_DIR / budget_year / "bp3.pdf"
    if not path.exists():
        raise FileNotFoundError(f"No BP3 PDF for {budget_year}: {path}")

    doc = fitz.open(str(path))
    try:
        hit = _find_table_page(doc)
        if hit is None:
            return pd.DataFrame()
        _page_no, text = hit
        pairs = _parse_table(text)
    finally:
        doc.close()

    if not pairs:
        return pd.DataFrame()

    return pd.DataFrame(
        [
            {
                "budget_year": budget_year,
                "fiscal_year": fy,
                "line_item": "Net overseas migration",
                "measure": "persons",
                "value": v,
            }
            for fy, v in pairs
        ]
    )
