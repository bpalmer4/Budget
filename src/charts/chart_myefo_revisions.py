"""Latest MYEFO vs its Budget: revisions to revenue, expenditure and the balance.

Two grouped bar charts for the most recent MYEFO, one bar group per fiscal
year in the forward estimates:

- **Cash** — Receipts, Payments, Underlying cash balance.
- **Accrual** — Revenue, Expenses, Net operating balance.

Each bar is MYEFO − Budget ($b), both published for the same budget year.
Expenditure bars are the raw change (up = more spending), so for each year
revenue bar − expenditure bar = balance bar, within rounding; this is
checked and printed.

Run:
    uv run python -m src.charts.chart_myefo_revisions
"""

import mgplot as mg
import pandas as pd

from src.utilities.paths import PARQUET_DIR, ROOT

_CHECK_TOLERANCE_B = 0.2  # aggregates are published to $0.1b, so two rounded differences can be 0.2 apart
_BASES: dict[str, tuple[str, str, str]] = {
    "Cash": ("Receipts", "Payments", "Underlying cash balance"),
    "Accrual": ("Revenue", "Expenses", "Net operating balance"),
}


def _read(name: str, budget_year: str) -> pd.DataFrame:
    df = pd.read_parquet(PARQUET_DIR / name)
    return df[(df["measure"] == "$b") & (df["budget_year"] == budget_year)]


def _revisions(budget_year: str, line_items: tuple[str, ...]) -> pd.DataFrame:
    """MYEFO − Budget ($b): rows are fiscal years, columns are line items."""
    myefo = _read("myefo_estimates.parquet", budget_year)
    budget = _read("bp1_estimates.parquet", budget_year)
    m = myefo.pivot_table(index="fiscal_year", columns="line_item", values="value")
    b = budget.pivot_table(index="fiscal_year", columns="line_item", values="value")
    missing = [li for li in line_items if li not in m.columns or li not in b.columns]
    if missing:
        raise ValueError(f"{budget_year}: line items missing from MYEFO or BP1: {missing}")
    # MYEFO years only: BP1 also covers earlier years that MYEFO does not revise.
    return (m.loc[:, list(line_items)] - b.reindex(m.index).loc[:, list(line_items)]).round(1)


def _check(revisions: pd.DataFrame, line_items: tuple[str, str, str]) -> None:
    revenue, expenditure, balance = line_items
    implied = revisions[revenue] - revisions[expenditure]
    for fy, gap in (implied - revisions[balance]).items():
        status = "ok" if abs(gap) <= _CHECK_TOLERANCE_B else "MISMATCH"
        print(f"  {fy}: {revenue} − {expenditure} vs {balance}: off by {gap:+.1f} $b  {status}")


def _plot(revisions: pd.DataFrame, basis: str, budget_year: str) -> None:
    ax = mg.bar_plot(revisions, annotate=True, above=True, rounding=1)
    title = f"{budget_year} MYEFO revisions to the Budget: {basis}"
    mg.finalise_plot(
        ax,
        title=title,
        filename=f"Australian Government {title}",
        ylabel="MYEFO less Budget ($ billion)",
        xlabel=None,
        y0=True,
        lheader="Up: higher in MYEFO than in the Budget.",
        lfooter=f"Australia. General government sector. {basis}.",
        rfooter=f"Source: Treasury {budget_year} BP1 + MYEFO",
        legend=True,
        show=False,
    )


def main() -> None:
    """Draw the cash and accrual revision charts for the latest MYEFO."""
    budget_year = max(pd.read_parquet(PARQUET_DIR / "myefo_estimates.parquet")["budget_year"])
    print(f"Latest MYEFO: {budget_year}")
    mg.set_chart_dir(str(ROOT / "charts"))
    for basis, line_items in _BASES.items():
        revisions = _revisions(budget_year, line_items)
        print(f"\n{basis} ($b, MYEFO − Budget):\n{revisions.to_string()}")
        _check(revisions, line_items)
        _plot(revisions, basis, budget_year)


if __name__ == "__main__":
    main()
