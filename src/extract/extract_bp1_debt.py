"""Extract BP1 Net debt and Gross debt forecasts for every budget.

Writes `data/parquet/bp1_debt.parquet`. The chart functions load this alongside
`bp1_estimates.parquet` so the orange forward-estimate lines extend back to
the earliest BP1.

Run:
    uv run python -m src.extract.extract_bp1_debt
"""

from __future__ import annotations

import sys

import pandas as pd

from src.data.bp1_debt import load_bp1_debt
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
        print(f"No BP1 PDFs under {BUDGET_DIR}", file=sys.stderr)
        return 1

    print(f"Extracting BP1 debt forecasts for {len(budgets)} budget(s)\n")
    frames: list[pd.DataFrame] = []
    for budget_year in budgets:
        try:
            df = load_bp1_debt(budget_year)
        except Exception as exc:  # noqa: BLE001
            print(f"  {budget_year}: FAILED  ({type(exc).__name__}: {exc})",
                  file=sys.stderr)
            continue
        n_net = len(df[df["line_item"] == "Net debt"]) if not df.empty else 0
        n_gross = len(df[df["line_item"] == "Gross debt"]) if not df.empty else 0
        print(f"  {budget_year}: Net debt={n_net} rows, Gross debt={n_gross} rows")
        frames.append(df)

    if not frames:
        print("\nNo data extracted.", file=sys.stderr)
        return 1

    combined = pd.concat(frames, ignore_index=True)
    PARQUET_DIR.mkdir(exist_ok=True)
    out = PARQUET_DIR / "bp1_debt.parquet"
    combined.to_parquet(out, index=False)
    print(f"\nWrote {len(combined)} rows to {out.relative_to(PARQUET_DIR.parent.parent)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
