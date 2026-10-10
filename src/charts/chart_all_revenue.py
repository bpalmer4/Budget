"""Chart every head of accrual revenue: FBO actuals + BP1 estimates.

One PNG per head found in `fbo_revenue.parquet` or `bp1_revenue.parquet`,
written to `charts/`. Heads that only existed for a few years (carbon pricing
mechanism, MRRT, the pre-2014 excise/customs split) simply draw short lines.

BP1 publishes revenue by head only for the year it is delivered in and the
budget year, so each Budget contributes a two-point line.

Run:
    uv run python -m src.charts.chart_all_revenue
"""

import pandas as pd

from src.charts.aggregate import plot_aggregate
from src.utilities.paths import PARQUET_DIR

_SOURCES = ("fbo_revenue.parquet", "bp1_revenue.parquet")


def _heads() -> list[str]:
    """Every head, in the order it first appears (FBO table order, then BP1-only heads)."""
    seen: dict[str, None] = {}
    for name in _SOURCES:
        for head in pd.read_parquet(PARQUET_DIR / name)["line_item"]:
            seen.setdefault(head, None)
    return list(seen)


def _title(head: str) -> str:
    # Category first, so the PNGs (named from the title) sort together.
    return f"Australian Government Revenue: {head}"


def main() -> None:
    """Plot every head of revenue, reporting failures without stopping."""
    for head in _heads():
        try:
            plot_aggregate(head, title=_title(head), start_before_budget_year=True)
            print(f"  ok    {head}")
        except Exception as exc:  # noqa: BLE001 - surface any failures, keep looping
            print(f"  FAIL  {head}: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
