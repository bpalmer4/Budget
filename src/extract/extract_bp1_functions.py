"""Extract BP1 expenses-by-function (top-level 14 categories) for every budget.

Run:
    uv run python -m src.extract.extract_bp1_functions
"""

from __future__ import annotations

import sys

import pandas as pd

from src.data.bp1_function import load_bp1_functions
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

    print(f"Extracting BP1 by-function expenses for {len(budgets)} budget(s)\n")

    frames: list[pd.DataFrame] = []
    for budget_year in budgets:
        try:
            df = load_bp1_functions(budget_year)
        except Exception as exc:  # noqa: BLE001
            print(f"  {budget_year}: FAILED  ({type(exc).__name__}: {exc})", file=sys.stderr)
            continue
        print(f"  {budget_year}: {len(df):3d} rows  "
              f"({df['line_item'].nunique()} functions × {df['fiscal_year'].nunique()} fiscal years)")
        frames.append(df)

    if not frames:
        print("\nNo data extracted.", file=sys.stderr)
        return 1

    combined = pd.concat(frames, ignore_index=True)
    PARQUET_DIR.mkdir(exist_ok=True)
    out = PARQUET_DIR / "bp1_functions.parquet"
    combined.to_parquet(out, index=False)

    print(f"\nWrote {len(combined)} rows to {out.relative_to(PARQUET_DIR.parent.parent)}")
    print(f"Budgets covered:   {len(combined['budget_year'].unique())}")
    print(f"Unique functions:  {combined['line_item'].nunique()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
