"""Path conventions for the Budget project.

All data living under `data/` is located by these helpers rather than by hard-coding
paths across the codebase. See `data/DATA_POLICY.md` for the directory layout.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DATA = ROOT / "data"
BUDGET_DIR = DATA / "Budget"
OUTCOME_DIR = DATA / "Outcome"
MYEFO_DIR = DATA / "MYEFO"
PARQUET_DIR = DATA / "parquet"


def fbo_part_path(year: str, part: str) -> Path:
    """Path to one FBO DOCX part for a fiscal year.

    `part` is the suffix used in the filename, e.g. ``"01_part_1"`` or
    ``"06_appendix_b"`` — the upstream archive's naming convention.
    """
    return OUTCOME_DIR / year / f"fbo_{part}.docx"


def bp1_statement_path(year: str, statement_no: int) -> Path:
    """Path to one BP1 statement DOCX for a budget year."""
    return BUDGET_DIR / year / f"bp1_bs-{statement_no}.docx"
