"""Extract BP1 Statement 1 (Overview) Table 1.1: Major Economic Parameters.

DOCX path is preferred where `bp1_bs-1.docx` is available (4 budgets:
2022-23, 2024-25, 2025-26, 2026-27); other budgets fall back to PDF. Same
DOCX-then-PDF dispatch pattern as `extract_fbo.py`.

Output extends the forecast horizon for the 6 major series (Real GDP,
Employment, Unemployment rate, CPI, WPI, Nominal GDP) beyond what's in
`bp1_economic.parquet` (Statement 2 Table 2.2). Chart layer reads both
parquets transparently.

Run:
    uv run python -m src.extract.extract_bp1_overview
"""

from __future__ import annotations

import sys

import pandas as pd

from src.data import bp1_overview_docx, bp1_overview_pdf
from src.utilities.paths import BUDGET_DIR, PARQUET_DIR


def _discover_budgets() -> list[tuple[str, str]]:
    """Return [(budget_year, source), ...] sorted by year. Source = 'docx' or 'pdf'."""
    if not BUDGET_DIR.is_dir():
        return []
    out: list[tuple[str, str]] = []
    for d in sorted(BUDGET_DIR.iterdir()):
        if not d.is_dir():
            continue
        if (d / "bp1_bs-1.docx").exists():
            out.append((d.name, "docx"))
        elif (d / "bp1.pdf").exists():
            out.append((d.name, "pdf"))
    return out


def main() -> int:
    targets = _discover_budgets()
    if not targets:
        print(f"No BP1 sources under {BUDGET_DIR}", file=sys.stderr)
        return 1

    n_docx = sum(1 for _, s in targets if s == "docx")
    n_pdf = sum(1 for _, s in targets if s == "pdf")
    print(f"Extracting BP1 overview (Table 1.1) for {len(targets)} budget(s): "
          f"{n_docx} DOCX, {n_pdf} PDF\n")

    frames: list[pd.DataFrame] = []
    for budget_year, source in targets:
        loader = (
            bp1_overview_docx.load_bp1_overview if source == "docx"
            else bp1_overview_pdf.load_bp1_overview
        )
        try:
            df = loader(budget_year)
        except Exception as exc:  # noqa: BLE001 - top-level extract: surface every failure
            print(f"  {budget_year} ({source}): FAILED  ({type(exc).__name__}: {exc})",
                  file=sys.stderr)
            continue
        n_items = df["line_item"].nunique() if not df.empty else 0
        n_years = df["fiscal_year"].nunique() if not df.empty else 0
        print(f"  {budget_year} ({source}): {len(df):3d} rows  "
              f"({n_items} line items × {n_years} fiscal years)")
        frames.append(df)

    if not frames:
        print("\nNo data extracted.", file=sys.stderr)
        return 1

    combined = pd.concat(frames, ignore_index=True)
    PARQUET_DIR.mkdir(exist_ok=True)
    out = PARQUET_DIR / "bp1_overview.parquet"
    combined.to_parquet(out, index=False)
    print(f"\nWrote {len(combined)} rows to {out.relative_to(PARQUET_DIR.parent.parent)}")
    print(f"Budget years: {', '.join(sorted(combined['budget_year'].unique()))}")
    print(f"Line items:   {', '.join(sorted(combined['line_item'].unique()))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
