"""Plot BP1 Table 1.1 economic forecasts against ABS actuals.

For each of the 6 major series, layers:
- **Black** — ABS history at its native frequency (quarterly or monthly),
  transformed per Treasury's footnote (see `src.charts.abs_history`).
- **Orange** — forecast trajectories from every BP1, unioning
  `bp1_economic.parquet` (Statement 2 detailed forecasts, 3 forwards) and
  `bp1_overview.parquet` (Statement 1 Table 1.1, up to 5 forwards). Each BP1
  becomes one line through annual points anchored at the Jun period of each
  fiscal year.

Frequency auto-detected from the history Series: quarterly series get
Q-DEC-Q2 anchors for the BP1 annual points; monthly series get M-Jun anchors.

- **Blue** — Estimated-actual bridge for the latest BP1, drawn only when ABS
  hasn't yet observed the full Est-actual FY. Connects the last ABS point
  to Treasury's BY-1 forecast at the Jun anchor of that FY. Matches the
  fiscal-aggregates chart's "blue bridge" convention.
"""

from __future__ import annotations

import mgplot as mg
import pandas as pd

from src.charts.abs_history import fetch_history
from src.utilities.paths import PARQUET_DIR, ROOT

_BP1_SOURCES = ("bp1_economic.parquet", "bp1_overview.parquet")


# National Accounts $-denominated series — used to add the CVM/CP qualifier
# to the chart footer. Index series (Terms of trade, GDP deflator) sit
# outside both sets.
_CVM_SERIES = frozenset(
    {
        "Real gross domestic product",
        "Household consumption",
        "Dwelling investment",
        "Total business investment",
        "Public final demand",
        "Private final demand",
        "Mining investment",
        "Non-mining investment",
        "Gross national expenditure",
        "Exports of goods and services",
        "Imports of goods and services",
    }
)
_CP_SERIES = frozenset({"Nominal gross domestic product"})
_MIN_POINTS = 2  # a Budget's forecast line is drawn only with at least this many points

# Default y-axis label by measure; any other measure is annual growth.
_YLABELS = {
    "%": "Per cent",
    "persons": "Thousand persons",
    "% pt contribution": "Percentage points",
    "% of GDP": "Per cent of GDP",
}

# Default left footer for line items with their own wording.
_LFOOTERS = {
    "Change in inventories": (
        "Australia. Chain volume measures. Annual contribution to FY-on-FY real GDP growth, percentage points. "
    ),
    "Current account balance (per cent of GDP)": (
        "Australia. FY-total current account balance as a share of FY-total nominal GDP, seasonally adjusted. "
    ),
    "Employment": "Australia. Through-the-year growth, monthly LFS, seasonally adjusted. ",
    "Consumer price index": "Australia. Through-the-year growth, quarterly index, seasonally adjusted. ",
    "Wage price index": "Australia. Through-the-year growth, quarterly index, seasonally adjusted. ",
    "Net overseas migration": (
        "Australia. Rolling 4-quarter sum of ABS quarterly NOM, original (not seasonally adjusted). "
    ),
}


def _fy_anchor_period(fy: str, freq: str) -> pd.Period:
    """Map a fiscal-year string to the Period at which Treasury's annual figure is plotted.

    For quarterly history: end-FY = Jun quarter = `YYYY-Q2`.
    For monthly history:   end-FY = Jun month   = `YYYY-06`.
    """
    end_year = int(fy.split("-", maxsplit=1)[0]) + 1
    if freq.startswith("Q"):
        return pd.Period(f"{end_year}Q2", freq=freq)
    if freq.startswith("M"):
        return pd.Period(f"{end_year}-06", freq=freq)
    raise ValueError(f"Unsupported chart frequency: {freq!r}")


def _measure_for(line_item: str) -> str:
    if "Unemployment rate" in line_item or "Participation rate" in line_item:
        return "%"
    if line_item == "Net overseas migration":
        return "persons"
    if line_item == "Change in inventories":
        return "% pt contribution"
    if line_item == "Current account balance (per cent of GDP)":
        return "% of GDP"
    return "% change"


def _default_lfooter(line_item: str) -> str:
    """Return the default left footer for one line item."""
    if "Unemployment rate" in line_item or "Participation rate" in line_item:
        return "Australia. Monthly seasonally-adjusted rate. "
    if line_item in _LFOOTERS:
        return _LFOOTERS[line_item]
    # GDPs and demand-side aggregates
    if line_item in _CVM_SERIES:
        qualifier, aggregation = "Chain volume measures. ", "rolling sum"
    elif line_item in _CP_SERIES:
        qualifier, aggregation = "Current prices. ", "rolling sum"
    else:  # Index series (Terms of trade, GDP deflator)
        qualifier, aggregation = "", "rolling average"
    return f"Australia. {qualifier}Year-on-year growth of 4-quarter {aggregation}, seasonally adjusted. "


def _load_bp1_forecasts(line_item: str, measure: str, sources: tuple[str, ...] = _BP1_SOURCES) -> pd.DataFrame:
    """Union forecast rows for one (line_item, measure) from each parquet in `sources`.

    Default `sources` is the BP1 pair; the BP3 NOM chart overrides it to pull
    from `bp3_nom.parquet` only. For shared (budget_year, fiscal_year) entries
    across the bundled parquets we drop duplicates afterwards.
    """
    frames: list[pd.DataFrame] = []
    for fname in sources:
        path = PARQUET_DIR / fname
        if not path.exists():
            continue
        df = pd.read_parquet(path)
        df = df[(df["line_item"] == line_item) & (df["measure"] == measure)]
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    return out.drop_duplicates(subset=["budget_year", "fiscal_year"])


def _fy_start_year(fy: str) -> int:
    return int(fy.split("-", maxsplit=1)[0])


def _by_minus_1(by: str) -> str:
    """Fiscal-year label for BY-1 (e.g. '2026-27' → '2025-26')."""
    start = _fy_start_year(by)
    return f"{start - 1}-{str(start)[-2:]}"


def _build_forward_series(bp1: pd.DataFrame, freq: str) -> list[pd.Series]:
    """One Series per BP1 — values plotted at the Jun anchor period of each FY.

    Only includes the budget year onward (BY, BY+1, BY+2, …). Outcome
    (FY <= BY-2) and Estimated-actual (FY = BY-1) are excluded — the
    est-actual is shown as a blue bridge layer for the most recent BP1 only
    (see `_build_bridge`).
    """
    out: list[pd.Series] = []
    for budget_year in sorted(bp1["budget_year"].unique()):
        by_start = _fy_start_year(budget_year)
        sub = bp1[
            (bp1["budget_year"] == budget_year) & (bp1["fiscal_year"].apply(_fy_start_year) >= by_start)
        ].sort_values("fiscal_year")
        if len(sub) < _MIN_POINTS:
            continue
        periods = [_fy_anchor_period(fy, freq) for fy in sub["fiscal_year"]]
        out.append(
            pd.Series(
                sub["value"].values,
                index=pd.PeriodIndex(periods, freq=freq),
                name=f"_fwd_{budget_year}",
            )
        )
    return out


def _build_bridge(history: pd.Series, bp1: pd.DataFrame, freq: str) -> pd.Series | None:
    """Blue 'Estimated actual' bridge for the latest BP1.

    Drawn only when ABS history hasn't reached the end of BY-1's fiscal year.
    Returns a 2-point Series from (last ABS observation, last ABS value) to
    (Jun anchor of BY-1, Treasury's est-actual value).

    Returns None if:
    - No BP1 data, or
    - The latest BP1 has no BY-1 row (e.g. October budgets where BY-1 is
      already an Outcome and not in the parquet), or
    - ABS history already covers end-of-BY-1 (no gap to bridge).
    """
    if history.empty or bp1.empty:
        return None
    latest_by = max(bp1["budget_year"].unique())
    eact_fy = _by_minus_1(latest_by)
    eact_rows = bp1[(bp1["budget_year"] == latest_by) & (bp1["fiscal_year"] == eact_fy)]
    if eact_rows.empty:
        return None
    eact_period = _fy_anchor_period(eact_fy, freq)
    last_period = history.index[-1]
    if last_period >= eact_period:
        return None  # ABS has already covered the est-actual year
    return pd.Series(
        [float(history.iloc[-1]), float(eact_rows.iloc[0]["value"])],
        index=pd.PeriodIndex([last_period, eact_period], freq=freq),
        name="Estimated actual",
    )


def plot_economic_forecast(
    line_item: str,
    *,
    title: str | None = None,
    ylabel: str | None = None,
    lfooter: str | None = None,
    rfooter: str = "Sources: ABS; Treasury BP1.",
    history_start_year: int = 2010,
    sources: tuple[str, ...] = _BP1_SOURCES,
) -> None:
    """Build and save the black-history + orange-forecasts chart for one of the six BP1 Table 1.1 economic parameters.

    Saves to `charts/{slugified-title}.png`.
    """
    measure = _measure_for(line_item)

    history = fetch_history(line_item).dropna()
    if history.empty:
        raise ValueError(f"No ABS history for {line_item!r}")
    if not isinstance(history.index, pd.PeriodIndex):
        raise TypeError(f"History series for {line_item!r} has no PeriodIndex freq.")
    freq = history.index.freqstr

    # Trim history to chart window. Start at 1 July of `history_start_year`,
    # i.e. the start of FY `{year}-{year+1}` — aligns the left edge with the
    # first BP1 in the forecast fan.
    start_period = (
        pd.Period(f"{history_start_year}-07", freq=freq)
        if freq.startswith("M")
        else pd.Period(f"{history_start_year}Q3", freq=freq)
    )
    history = history.loc[history.index >= start_period]
    history.name = "Actual"

    bp1 = _load_bp1_forecasts(line_item, measure, sources=sources)
    if measure == "persons":
        history = (history / 1000.0).rename("Actual")
        bp1 = bp1.assign(value=bp1["value"] / 1000.0)
    forwards = _build_forward_series(bp1, freq)
    bridge = _build_bridge(history, bp1, freq)

    if title is None:
        title = f"BP1 forecasts vs ABS actuals: {line_item}"
    if ylabel is None:
        ylabel = _YLABELS.get(measure, "Annual % growth")
    if lfooter is None:
        lfooter = _default_lfooter(line_item)

    mg.set_chart_dir(str(ROOT / "charts"))

    ax = mg.line_plot(
        history,
        color=["black"],
        width=2.0,
        annotate=False,
        label_series=[True],
    )

    if bridge is not None:
        ax = mg.line_plot(
            bridge,
            ax=ax,
            color=["blue"],
            width=1.5,
            annotate=False,
            label_series=[True],
        )

    for i, forward in enumerate(forwards):
        if i == 0:
            series = forward.rename("Forward estimates")
            label = [True]
        else:
            series = forward
            label = [False]
        ax = mg.line_plot(
            series,
            ax=ax,
            color=["darkorange"],
            width=1.0,
            alpha=0.7,
            marker="o",
            markersize=3,
            annotate=False,
            label_series=label,
        )

    mg.finalise_plot(
        ax,
        title=title,
        ylabel=ylabel,
        xlabel=None,
        rfooter=rfooter,
        lfooter=lfooter,
        legend=True,
        y0=True,
        show=False,
    )
