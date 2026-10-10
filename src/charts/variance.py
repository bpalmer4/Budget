"""Reusable plot of 1/2/3-year-ahead forecast miss (%) for one budget aggregate.

For each fiscal year with an FBO outcome, compute the percentage miss of
Treasury's forecast at three horizons:

- **1-year-ahead** — estimate from the BP1 published 1 year before the fiscal year
  (this year is the *1st forward* in that BP1).
- **2-year-ahead** — from the BP1 2 years before (this year is the *2nd forward*).
- **3-year-ahead** — from the BP1 3 years before (this year is the *3rd forward*).

Percentage miss = (outcome − estimate) / estimate × 100. Positive means the
outcome exceeded the forecast (Treasury under-forecast). Negative means the
outcome fell short (Treasury over-forecast).

Note: percentage miss is only meaningful for monotonically-positive variables
(Receipts, Payments, Revenue, Expenses, etc.). For variables that can be
negative or cross zero (Underlying cash balance, Fiscal balance), the
denominator can collapse or flip sign — prefer raw differences for those.
"""

from __future__ import annotations

import mgplot as mg
import pandas as pd

from src.utilities.paths import PARQUET_DIR, ROOT


def _fy_period(fy: str) -> pd.Period:
    return pd.Period(fy.split("-", maxsplit=1)[0], freq="Y")


def _fy_year(fy: str) -> int:
    return int(fy.split("-", maxsplit=1)[0])


def _read_existing(names: tuple[str, ...]) -> list[pd.DataFrame]:
    """Read each named parquet that exists in `PARQUET_DIR`."""
    return [pd.read_parquet(PARQUET_DIR / n) for n in names if (PARQUET_DIR / n).exists()]


def plot_variance(
    line_item: str,
    measure: str = "$b",
    *,
    horizons: tuple[int, ...] = (1, 2, 3),
    title: str | None = None,
    lfooter: str = "Australia. General government sector. Positive: outcome exceeded forecast.",
    rfooter: str = "Source: Treasury BP1 + Final Budget Outcome",
) -> None:
    """Build and save the 1/2/3-year-ahead forecast-miss chart for one aggregate.

    Args:
        line_item: e.g. "Expenses", "Revenue", "Receipts", "Payments".
        measure: "$b" (default) or "Per cent of GDP".
        horizons: which forecast horizons to plot (years ahead).
        title: chart title; defaults to "{line_item}: forecast miss".
        lfooter: left footer, passed through to `finalise_plot`.
        rfooter: right footer, passed through to `finalise_plot`.

    """
    fbo = pd.concat(
        _read_existing(("fbo_outcomes.parquet", "fbo_functions.parquet", "fbo_debt.parquet")), ignore_index=True
    )
    bp1 = pd.concat(_read_existing(("bp1_estimates.parquet", "bp1_functions.parquet")), ignore_index=True)
    fbo = fbo.query("line_item == @line_item and measure == @measure")
    bp1 = bp1.query("line_item == @line_item and measure == @measure").copy()

    if fbo.empty or bp1.empty:
        raise ValueError(
            f"Need both FBO and BP1 data for {line_item!r}/{measure!r}; FBO rows={len(fbo)}, BP1 rows={len(bp1)}"
        )

    outcomes = fbo.set_index("fiscal_year")["value"]
    bp1["horizon"] = bp1["fiscal_year"].map(_fy_year) - bp1["budget_year"].map(_fy_year)
    bp1["outcome"] = bp1["fiscal_year"].map(outcomes)
    bp1 = bp1.dropna(subset=["outcome"])
    bp1 = bp1[bp1["horizon"].isin(horizons)]
    bp1["pct_miss"] = (bp1["outcome"] - bp1["value"]) / bp1["value"] * 100
    bp1["period"] = pd.PeriodIndex([_fy_period(fy) for fy in bp1["fiscal_year"]], freq="Y")

    if bp1.duplicated(["period", "horizon"]).any():
        raise ValueError(f"Duplicate forecasts for {line_item!r} by period and horizon")
    wide = bp1.pivot_table(index="period", columns="horizon", values="pct_miss").sort_index()
    wide.columns = [f"{int(h)}-year-ahead" for h in wide.columns]

    if title is None:
        title = f"{line_item}: forecast miss"

    mg.set_chart_dir(str(ROOT / "charts"))

    ax = mg.line_plot(wide, width=2.0, annotate=False)

    mg.finalise_plot(
        ax,
        title=title,
        ylabel="Forecast miss (%)",
        xlabel="Financial year beginning July",
        axhline={"y": 0, "color": "#555555", "linewidth": 1, "linestyle": "--"},
        rfooter=rfooter,
        lfooter=lfooter,
        legend=True,
        show=False,
    )
