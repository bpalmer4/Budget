"""Chart post-2022 BP3 NOM forecasts against ABS actuals, one colour per Budget.

Companion to `chart_nom_bp3.py`, which fans all 17 BP3s in a single orange and
starts each trajectory at the budget year. This chart narrows to the five
post-2022 Budgets and draws each in its own colour, running from the
**estimated actual** (BY-1) all the way through the final forward estimate — so
the whole published trajectory is visible, not just the forwards.

Run:
    uv run python -m src.charts.chart_nom_recent
"""

from __future__ import annotations

from typing import NotRequired, TypedDict

import mgplot as mg
import pandas as pd

from src.charts.abs_history import fetch_history
from src.charts.economic import _fy_anchor_period, _fy_start_year
from src.utilities.paths import PARQUET_DIR, ROOT

LINE_ITEM = "Net overseas migration"
MEASURE = "persons"
SOURCE = "bp3_nom.parquet"
FIRST_BUDGET_YEAR = 2022  # first FY start-year of the Budgets charted
HISTORY_START_YEAR = 2016  # 1 July of this year is the left edge of the chart
MIN_POINTS = 2  # a Budget's line is drawn only with at least this many points


class _BudgetStyle(TypedDict):
    """Line style for one Budget vintage."""

    color: str
    style: str
    marker: str
    width: float
    dashes: NotRequired[tuple[int, tuple[int, ...]]]  # matplotlib (offset, on-off sequence)


# One style per Budget, in chronological order. Colour, dash pattern and
# marker shape all vary together — three redundant cues, so the vintages stay
# separable where lines overlap, and in greyscale.
#
# matplotlib offers four dash patterns and there are five Budgets: the four
# older vintages take the dashes, and the current Budget is drawn solid and
# heavier, which also marks it out as the live set of estimates.
BUDGET_STYLES: tuple[_BudgetStyle, ...] = (
    {"color": "#1b9e77", "style": ":", "marker": "o", "width": 1.6},  # 2022-23
    {"color": "#d95f02", "style": "-.", "marker": "s", "width": 1.6},  # 2023-24
    {"color": "#7570b3", "style": "--", "marker": "^", "width": 1.6},  # 2024-25
    # mgplot validates `style` as a string, so this vintage asks for a plain
    # dash and the long-dash-dot pattern is applied to the artist afterwards.
    {"color": "#e7298a", "style": "--", "marker": "D", "width": 1.6, "dashes": (0, (7, 2, 1, 2))},  # 2025-26
    {"color": "#0072b2", "style": "-", "marker": "v", "width": 2.6},  # 2026-27
)


def _load_recent_forecasts() -> pd.DataFrame:
    """BP3 NOM rows for Budgets from `FIRST_BUDGET_YEAR` onwards."""
    df = pd.read_parquet(PARQUET_DIR / SOURCE)
    df = df.query("line_item == @LINE_ITEM and measure == @MEASURE")
    keep = df["budget_year"].apply(_fy_start_year) >= FIRST_BUDGET_YEAR
    return df[keep]


def _build_budget_series(df: pd.DataFrame, freq: str) -> list[pd.Series]:
    """One Series per Budget, from the estimated actual (BY-1) onwards.

    Rows earlier than BY-1 are outcomes already in the ABS history layer, so
    they are trimmed to keep every line starting at the same point in its own
    budget cycle.
    """
    out: list[pd.Series] = []
    for budget_year in sorted(df["budget_year"].unique()):
        by_start = _fy_start_year(budget_year)
        sub = df[
            (df["budget_year"] == budget_year) & (df["fiscal_year"].apply(_fy_start_year) >= by_start - 1)
        ].sort_values("fiscal_year")
        if len(sub) < MIN_POINTS:
            continue
        periods = [_fy_anchor_period(fy, freq) for fy in sub["fiscal_year"]]
        out.append(
            pd.Series(
                sub["value"].to_numpy() / 1000.0,
                index=pd.PeriodIndex(periods, freq=freq),
                name=f"{budget_year} Budget",
            )
        )
    return out


def render() -> None:
    """Chart the post-2022 BP3 Net overseas migration forecasts, one colour per Budget, against ABS actuals."""
    history = fetch_history(LINE_ITEM).dropna()
    if history.empty:
        raise ValueError(f"No ABS history for {LINE_ITEM!r}")
    if not isinstance(history.index, pd.PeriodIndex):
        raise TypeError(f"History series for {LINE_ITEM!r} has no PeriodIndex freq.")
    freq = history.index.freqstr

    start_period = (
        pd.Period(f"{HISTORY_START_YEAR}-07", freq=freq)
        if freq.startswith("M")
        else pd.Period(f"{HISTORY_START_YEAR}Q3", freq=freq)
    )
    history = history.loc[history.index >= start_period] / 1000.0
    history.name = "Actual"

    forecasts = _build_budget_series(_load_recent_forecasts(), freq)

    mg.set_chart_dir(str(ROOT / "charts"))

    ax = mg.line_plot(
        history,
        color=["black"],
        width=2.0,
        annotate=False,
        label_series=[True],
    )
    for series, style in zip(forecasts, BUDGET_STYLES, strict=False):
        ax = mg.line_plot(
            series,
            ax=ax,
            color=[style["color"]],
            style=[style["style"]],
            width=[style["width"]],
            marker=[style["marker"]],
            markersize=5,
            annotate=False,
            label_series=[True],
        )
        dashes = style.get("dashes")
        if isinstance(dashes, tuple):
            ax.lines[-1].set_linestyle(dashes)

    mg.finalise_plot(
        ax,
        title="BP3 forecasts vs ABS actuals: Net overseas migration (post-2022 Budgets)",
        ylabel="Thousand persons",
        xlabel=None,
        rfooter="Sources: ABS; Treasury BP3.",
        lfooter=(
            "Australia. Rolling 4-quarter sum of quarterly NOM, original. "
            "Budget lines: estimated actual to final forward estimate. "
        ),
        legend=True,
        y0=True,
        show=False,
    )


def main() -> None:
    """Draw the chart, reporting a failure instead of raising it."""
    try:
        render()
        print("  ok    Net overseas migration (post-2022 BP3s)")
    except Exception as exc:  # noqa: BLE001
        print(f"  FAIL  Net overseas migration (post-2022 BP3s): {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
