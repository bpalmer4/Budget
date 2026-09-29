"""Extract BP1 accrual revenue by head (two reconciliation tables per budget).

Each table is checked twice before it is kept:
- the heads (leaves added, refunds subtracted) must sum to its Total revenue;
- that Total revenue must match the Revenue aggregate in `bp1_estimates.parquet`,
  which comes from a different BP1 table.
"Total revenue" itself is then dropped — it duplicates the Revenue aggregate.

Run:
    uv run python -m src.extract.extract_bp1_revenue
"""

from __future__ import annotations

import sys

import pandas as pd

from src.data.bp1_revenue import load_bp1_revenue
from src.data.revenue_heads import TOTAL_REVENUE, additive_sum
from src.utilities.paths import BUDGET_DIR, PARQUET_DIR

SUM_TOLERANCE_B = 0.05  # heads vs Total revenue, $b (rounding of ~30 $m cells)
AGGREGATE_TOLERANCE_B = 0.06  # vs the aggregate, published to $0.1b


def _discover_budgets() -> list[str]:
    if not BUDGET_DIR.is_dir():
        return []
    return sorted(d.name for d in BUDGET_DIR.iterdir() if d.is_dir() and (d / "bp1.pdf").exists())


def _revenue_aggregate() -> pd.Series:
    est = pd.read_parquet(PARQUET_DIR / "bp1_estimates.parquet")
    est = est[(est["line_item"] == "Revenue") & (est["measure"] == "$b")]
    return est.set_index(["budget_year", "fiscal_year"])["value"]


def _check(df: pd.DataFrame, aggregate: pd.Series) -> list[str]:
    problems: list[str] = []
    for (budget_year, fiscal_year), group in df.groupby(["budget_year", "fiscal_year"]):
        values = dict(zip(group["line_item"], group["value"], strict=True))
        total = values.get(TOTAL_REVENUE)
        if total is None:
            problems.append(f"{fiscal_year}: no Total revenue row")
            continue
        heads = additive_sum(values)
        if abs(heads - total) > SUM_TOLERANCE_B:
            problems.append(f"{fiscal_year}: heads sum {heads:.3f} ≠ Total revenue {total:.3f}")
        agg = aggregate.get((budget_year, fiscal_year))
        if agg is not None and abs(agg - total) > AGGREGATE_TOLERANCE_B:
            problems.append(f"{fiscal_year}: Total revenue {total:.3f} ≠ Revenue aggregate {agg:.1f}")
    return problems


def main() -> int:
    """Extract, check and write `bp1_revenue.parquet`."""
    budgets = _discover_budgets()
    if not budgets:
        print(f"No BP1 PDFs found under {BUDGET_DIR}", file=sys.stderr)
        return 1

    print(f"Extracting BP1 accrual revenue by head for {len(budgets)} budget(s)\n")
    aggregate = _revenue_aggregate()

    frames: list[pd.DataFrame] = []
    for budget_year in budgets:
        try:
            df = load_bp1_revenue(budget_year)
        except Exception as exc:  # noqa: BLE001 - report and keep going
            print(f"  {budget_year}: FAILED  ({type(exc).__name__}: {exc})", file=sys.stderr)
            continue
        problems = _check(df, aggregate)
        status = "ok" if not problems else "CHECK FAILED: " + "; ".join(problems)
        print(f"  {budget_year}: {len(df):3d} rows  (fiscal years "
              f"{', '.join(sorted(df['fiscal_year'].unique()))})  {status}")
        frames.append(df[df["line_item"] != TOTAL_REVENUE])

    if not frames:
        print("\nNo data extracted.", file=sys.stderr)
        return 1

    combined = pd.concat(frames, ignore_index=True)
    PARQUET_DIR.mkdir(exist_ok=True)
    out = PARQUET_DIR / "bp1_revenue.parquet"
    combined.to_parquet(out, index=False)

    print(f"\nWrote {len(combined)} rows to {out.relative_to(PARQUET_DIR.parent.parent)}")
    print(f"Budgets covered:  {combined['budget_year'].nunique()}")
    print(f"Unique heads:     {combined['line_item'].nunique()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
