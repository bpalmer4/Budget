"""Extract BP1 forward estimates for every budget and write Parquet.

Scans `data/Budget/` for fiscal-year directories with a `bp1.pdf`, parses the
GFS aggregates table from each, and writes `data/parquet/bp1_estimates.parquet`.

Run:
    uv run python -m src.extract.extract_bp1
"""

from __future__ import annotations

import sys

import pandas as pd

from src.data.bp1_pdf import load_bp1_estimates
from src.utilities.paths import BUDGET_DIR, PARQUET_DIR


def _discover_budgets() -> list[str]:
    if not BUDGET_DIR.is_dir():
        return []
    return sorted(
        d.name for d in BUDGET_DIR.iterdir()
        if d.is_dir() and (d / "bp1.pdf").exists()
    )


def main() -> int:
    budgets = _discover_budgets()
    if not budgets:
        print(f"No BP1 PDFs found under {BUDGET_DIR}", file=sys.stderr)
        return 1

    print(f"Extracting BP1 estimates for {len(budgets)} budget(s): "
          f"{', '.join(budgets)}\n")

    frames: list[pd.DataFrame] = []
    for budget_year in budgets:
        try:
            df = load_bp1_estimates(budget_year)
        except Exception as exc:  # noqa: BLE001 - top-level extract, surface every failure
            print(f"  {budget_year}: FAILED  ({type(exc).__name__}: {exc})",
                  file=sys.stderr)
            continue
        n_fy = df["fiscal_year"].nunique()
        n_li = df["line_item"].nunique()
        print(f"  {budget_year}: {len(df):4d} rows  "
              f"({n_li:2d} line items × {n_fy} fiscal years)")
        frames.append(df)

    if not frames:
        print("\nNo data extracted.", file=sys.stderr)
        return 1

    combined = pd.concat(frames, ignore_index=True)
    PARQUET_DIR.mkdir(exist_ok=True)
    out = PARQUET_DIR / "bp1_estimates.parquet"
    combined.to_parquet(out, index=False)

    print(f"\nWrote {len(combined)} rows to {out.relative_to(PARQUET_DIR.parent.parent)}")
    print(f"Budgets covered:     {len(combined['budget_year'].unique())}")
    print(f"Fiscal year range:   {min(combined['fiscal_year'])} → {max(combined['fiscal_year'])}")
    print(f"Unique line items:   {combined['line_item'].nunique()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
