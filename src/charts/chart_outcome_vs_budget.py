"""Latest FBO outcome vs that year's Budget: over/under for every item.

Two horizontal bar charts for the most recent fiscal year with an FBO:

- **Expenses** — the 14 GFS functions.
- **Revenue** — every head of accrual revenue, excluding subtotals, so the
  bars add up to the total revenue gap.

Each bar is outcome − estimate ($b), where the estimate is the one published
in that year's own Budget (e.g. the 2025-26 Budget's figure for 2025-26).
Positive: the outcome came in above the Budget.

Two adjustments keep revenue like-for-like:

- Refunds (income tax refunds, customs refunds and drawbacks) are published as
  positive amounts that are subtracted; their bars are shown as the effect on
  revenue (more refunds than budgeted → a negative bar), labelled "less: ...".
- Where one side splits "Other customs duty" into Textiles, clothing and
  footwear / Passenger motor vehicles / Other imports (the 2025-26 Budget does,
  the 2025-26 FBO does not), the parts are summed into "Other customs duty".

As a check, the bars are summed and compared with the Expenses / Revenue
aggregate gap from the headline tables; the result is printed.

Run:
    uv run python -m src.charts.chart_outcome_vs_budget
"""

import mgplot as mg
import pandas as pd

from src.data.revenue_heads import DEDUCTIONS, NON_ADDITIVE, SUBTOTALS
from src.utilities.paths import PARQUET_DIR, ROOT

_CUSTOMS_TOTAL = "Other customs duty"
_CUSTOMS_PARTS = ("Textiles, clothing and footwear", "Passenger motor vehicles", "Other imports")
_ABOVE_COLOUR = "darkblue"
_BELOW_COLOUR = "darkorange"
_CHECK_TOLERANCE_B = 0.2  # bars vs aggregate gap, $b (aggregates are published to $0.1b)
# Figure size in inches: height grows with the number of bars so labels don't crowd.
_FIG_WIDTH = 9.0
_MIN_FIG_HEIGHT = 4.5
_INCHES_PER_BAR = 0.28
_FIG_PADDING = 1.5
_LABEL_MARGIN = 0.1  # x-axis padding each side, as a share of the data range


def _read(name: str) -> pd.DataFrame:
    df = pd.read_parquet(PARQUET_DIR / name)
    return df[df["measure"] == "$b"]


def _merge_customs(values: pd.Series) -> pd.Series:
    parts = [p for p in _CUSTOMS_PARTS if p in values.index]
    if not parts:
        return values
    merged = values.drop(parts)
    merged.loc[_CUSTOMS_TOTAL] = values[parts].sum()
    return merged


def _gap(bp1_file: str, fbo_file: str, fiscal_year: str) -> pd.Series:
    """Outcome − own-Budget estimate for every item present on both sides ($b)."""
    bp1 = _read(bp1_file)
    fbo = _read(fbo_file)
    estimate = bp1[(bp1["budget_year"] == fiscal_year) & (bp1["fiscal_year"] == fiscal_year)]
    outcome = fbo[fbo["fiscal_year"] == fiscal_year]
    est = _merge_customs(estimate.set_index("line_item")["value"])
    out = _merge_customs(outcome.set_index("line_item")["value"])
    unmatched = sorted(set(est.index) ^ set(out.index))
    if unmatched:
        print(f"  Not on both sides, left out: {unmatched}")
    return (out - est).dropna()


def _aggregate_gap(line_item: str, fiscal_year: str) -> float:
    bp1 = _read("bp1_estimates.parquet")
    fbo = _read("fbo_outcomes.parquet")
    est = bp1[
        (bp1["line_item"] == line_item) & (bp1["budget_year"] == fiscal_year) & (bp1["fiscal_year"] == fiscal_year)
    ]["value"]
    out = fbo[(fbo["line_item"] == line_item) & (fbo["fiscal_year"] == fiscal_year)]["value"]
    return float(out.iloc[0] - est.iloc[0])


def _revenue_bars(gap: pd.Series) -> pd.Series:
    keep = [h for h in gap.index if h not in SUBTOTALS and h not in NON_ADDITIVE]
    bars = gap[keep].copy()
    for head in DEDUCTIONS & set(bars.index):
        bars.loc[head] = -bars[head]
    return bars.rename(index={h: f"less: {h}" for h in DEDUCTIONS})


def _plot(bars: pd.Series, category: str, fiscal_year: str, check_line_item: str) -> None:
    total = float(bars.sum())
    aggregate = _aggregate_gap(check_line_item, fiscal_year)
    status = "ok" if abs(total - aggregate) <= _CHECK_TOLERANCE_B else "MISMATCH"
    print(f"  {category}: bars sum {total:+.2f} vs {check_line_item} gap {aggregate:+.1f} $b  {status}")

    bars = bars.sort_values()  # horizontal bars draw bottom-up: largest overrun on top
    colours = [_ABOVE_COLOUR if v >= 0 else _BELOW_COLOUR for v in bars]
    ax = mg.bar_plot(
        bars.to_frame("gap"), horizontal=True, color=colours, annotate=True, above=True, rounding=1, label_series=False
    )
    # Room beyond the longest bar on each side for its outside value label.
    lo, hi = min(float(bars.min()), 0.0), max(float(bars.max()), 0.0)
    margin = _LABEL_MARGIN * (hi - lo)
    title = f"{category}: {fiscal_year} outcome vs Budget"
    mg.finalise_plot(
        ax,
        title=title,
        # Explicit filename keeps the PNG sorting with the other category charts.
        filename=f"Australian Government {title}",
        xlabel=f"Outcome less {fiscal_year} Budget estimate ($ billion)",
        ylabel=None,
        x0=True,
        xlim=(lo - margin, hi + margin),
        figsize=(_FIG_WIDTH, max(_MIN_FIG_HEIGHT, _INCHES_PER_BAR * len(bars) + _FIG_PADDING)),
        lheader="Blue: above Budget. Orange: below.",
        rheader=f"Bars sum to {total:+.1f} $b",
        lfooter="Australia. General government sector. Accrual.",
        rfooter=f"Source: Treasury {fiscal_year} BP1 + FBO",
        show=False,
    )


def main() -> None:
    """Draw the expenses and revenue over/under charts for the latest FBO year."""
    fiscal_year = max(_read("fbo_functions.parquet")["fiscal_year"])
    print(f"Latest FBO: {fiscal_year}")
    mg.set_chart_dir(str(ROOT / "charts"))

    expenses = _gap("bp1_functions.parquet", "fbo_functions.parquet", fiscal_year)
    _plot(expenses, "Expenses", fiscal_year, "Expenses")

    revenue = _revenue_bars(_gap("bp1_revenue.parquet", "fbo_revenue.parquet", fiscal_year))
    _plot(revenue, "Revenue", fiscal_year, "Revenue")


if __name__ == "__main__":
    main()
