"""Shared helpers for the accrual revenue-by-head tables in BP1 and the FBO.

Both documents publish the same table shape: one row per head of revenue
(Gross income tax withholding, Company tax, GST, Petrol, Beer, ...), grouped
under header rows that carry no values, with subtotal rows along the way and
"Total revenue" as the last data row before an optional "Memorandum:" block.

Label handling is deliberately conservative: only unambiguous renames of the
*same* head are merged (e.g. "Superannuation funds" → "Superannuation fund
taxes", "Dividends" → "Dividends and distributions"). Heads that genuinely
differ between table generations — the pre-2014 "Resource rent taxes",
"Excise-like goods", "Other excisable products", sub-totals such as "Total
sales taxes" — are kept as their own short-lived line items.
"""

from __future__ import annotations

import re

TOTAL_REVENUE = "Total revenue"

# Same head, reworded between years or between BP1 and FBO. Keys are
# lower-cased labels after footnote/apostrophe clean-up.
_RENAMES: dict[str, str] = {
    "gross other individuals and trusts": "Gross other individuals",
    "less: refunds": "Income tax refunds",
    "total individuals and other withholding taxation": "Total individuals and other withholding tax",
    "superannuation funds": "Superannuation fund taxes",
    "dividends": "Dividends and distributions",
    "less: refunds and drawbacks": "Customs refunds and drawbacks",
    "of which: other excisable beverages": "Other excisable beverages",
    "major bank levy": "Major bank levy",  # 2022-23 BP1 capitalises it
}

# Rows that sum other rows. Excluded when checking that the heads add up.
SUBTOTALS: frozenset[str] = frozenset({
    "Total individuals and other withholding tax",
    "Income taxation revenue",
    "Total sales taxes",
    "Total excise duty revenue",
    "Total customs duty revenue",
    "Total excise and customs duty",
    "Total other indirect taxation revenue",
    "Indirect taxation revenue",
    "Taxation revenue",
    "Non-taxation revenue",
    TOTAL_REVENUE,
})
# Published as positive numbers but subtracted in the table's arithmetic.
DEDUCTIONS: frozenset[str] = frozenset({"Income tax refunds", "Customs refunds and drawbacks"})
# "Of which" rows are part of the row above, not additional to it.
NON_ADDITIVE: frozenset[str] = frozenset({"Other excisable beverages"})

_FOOTNOTE_RE = re.compile(r"(?:\s*\([a-z]\))+$")
# The 2021-22 BP1 PDF places some labels' first capital apart from the rest of
# the word, so text extraction yields "T otal revenue", "G oods and services tax".
# No head starts with a one-letter word, so a lone leading capital is rejoined.
_SPLIT_CAPITAL_RE = re.compile(r"^([A-Z]) (?=[a-z])")
# 2013-14 writes "Individuals' and other withholding taxes" (either case).
_POSSESSIVE_RE = re.compile(r"(individuals)['’]", re.IGNORECASE)
_NUMBER_RE = re.compile(r"^-?\d[\d,]*\.?\d*$")
_NA_TOKENS = {"-", "..", "na", "n.a.", "NA", "nfp"}


def canonical_head(raw: str) -> str:
    """Clean a table label and apply the rename map."""
    s = re.sub(r"\s+", " ", raw.replace("\xa0", " ")).strip()
    s = _SPLIT_CAPITAL_RE.sub(r"\1", s)
    s = _POSSESSIVE_RE.sub(r"\1", _FOOTNOTE_RE.sub("", s)).strip()
    return _RENAMES.get(s.lower(), s)


def parse_number(token: str) -> float | None:
    """Parse one numeric cell ('1,234', '-56', '(78)'); None for n/a or non-numeric."""
    s = (
        token.strip()
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
    return float(s) if _NUMBER_RE.match(s) else None


def split_text_row(line: str) -> tuple[str, list[float | None]]:
    """Split a PDF text row into (label, trailing numeric cells).

    Cells are read right to left until a token is neither a number nor an n/a
    marker; the rest is the label. A header row returns an empty cell list.
    """
    tokens = line.split()
    cells: list[float | None] = []
    i = len(tokens) - 1
    while i >= 0 and (tokens[i] in _NA_TOKENS or parse_number(tokens[i]) is not None):
        cells.append(parse_number(tokens[i]))
        i -= 1
    cells.reverse()
    return " ".join(tokens[: i + 1]), cells


def additive_sum(values: dict[str, float]) -> float:
    """Sum the heads the way the table does: leaves added, deductions subtracted."""
    total = 0.0
    for head, value in values.items():
        if head in SUBTOTALS or head in NON_ADDITIVE:
            continue
        total += -value if head in DEDUCTIONS else value
    return total
