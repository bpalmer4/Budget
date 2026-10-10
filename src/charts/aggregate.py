"""Reusable plot of one budget aggregate over time.

Renders three layers:

- **Actual** (black) — historical outcomes from the FBO parquet.
- **Estimated outcome (latest Budget)** (blue) — a one-segment bridge from the
  last FBO actual to the latest BP1's estimate of the just-completed fiscal year
  (the year before its budget year), drawn only while that year has no FBO yet
  (i.e. between the May Budget and the September FBO). Never a forecast.
- **Forward estimates** (dark orange) — one line per BP1, showing each Budget's
  forward-estimate trajectory (budget year + 3 projection years). Only the
  first such line is labelled in the legend.

X-axis is an annual PeriodIndex labelled by the start year of the fiscal year;
the xlabel "Financial year beginning July" makes the convention explicit.

Used by `chart_<aggregate>.py` entry-point scripts in this package.
"""

from __future__ import annotations

import mgplot as mg
import pandas as pd
from matplotlib.axes import Axes

from src.utilities.paths import PARQUET_DIR, ROOT


def _fy_period(fy: str) -> pd.Period:
    """FY string 'YYYY-YY' → annual Period labelled by its start year.

    Uses `freq='Y'` (calendar year) rather than `freq='A-JUN'` so mgplot's
    default year_labeller renders the *start* year on the axis — which combined
    with the "Financial year beginning July" xlabel reads naturally.
    """
    return pd.Period(fy.split("-", maxsplit=1)[0], freq="Y")


_BP1_SOURCES = (
    "bp1_estimates.parquet",
    "bp1_functions.parquet",
    "bp1_debt.parquet",
    "bp1_hcb.parquet",
    "bp1_revenue.parquet",
)
_MIN_LINE_POINTS = 2  # a line needs at least two points to draw
_FBO_SOURCES = (
    "fbo_outcomes.parquet",
    "fbo_functions.parquet",
    "fbo_debt.parquet",
    "fbo_hcb.parquet",
    "fbo_revenue.parquet",
)


def _load_all(sources: tuple[str, ...]) -> pd.DataFrame:
    """Concat every parquet in `sources` that exists.

    Aggregates and function data share the same schema so they merge transparently.
    """
    frames = [pd.read_parquet(PARQUET_DIR / f) for f in sources if (PARQUET_DIR / f).exists()]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _load_filtered(line_item: str, measure: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    fbo = _load_all(_FBO_SOURCES)
    bp1 = _load_all(_BP1_SOURCES)
    fbo = fbo[(fbo["line_item"] == line_item) & (fbo["measure"] == measure)].copy()
    bp1 = bp1[(bp1["line_item"] == line_item) & (bp1["measure"] == measure)].copy()
    # Some line items appear in more than one source parquet (e.g. Net debt is
    # in both bp1_estimates and bp1_debt for 2020-21+ BP1s). Dedupe defensively.
    if not fbo.empty:
        fbo = fbo.drop_duplicates(subset=["fiscal_year", "line_item", "measure"])
    if not bp1.empty:
        bp1 = bp1.drop_duplicates(subset=["budget_year", "fiscal_year", "line_item", "measure"])
    if not fbo.empty:
        fbo["period"] = pd.PeriodIndex([_fy_period(fy) for fy in fbo["fiscal_year"]], freq="Y")
    if not bp1.empty:
        bp1["period"] = pd.PeriodIndex([_fy_period(fy) for fy in bp1["fiscal_year"]], freq="Y")
    return fbo, bp1


def _build_actual(fbo: pd.DataFrame) -> pd.Series | None:
    # mgplot's line_plot raises on a one-point series, and one point is no line.
    if len(fbo) < _MIN_LINE_POINTS:
        return None
    return fbo.set_index("period")["value"].sort_index().rename("Actual")


def _build_bridge(actual: pd.Series | None, bp1: pd.DataFrame) -> pd.Series | None:
    """Bridge from the last actual to the latest Budget's estimate of a finished, pre-FBO year.

    Only years *before* the latest budget year qualify, so the bridge never
    ends on a forecast. Once the FBO for that year lands (September), there is
    no candidate and no bridge until the next Budget (May).
    """
    if actual is None or bp1.empty:
        return None
    latest_budget = max(bp1["budget_year"].unique())
    latest = bp1[bp1["budget_year"] == latest_budget]
    candidates = latest[
        (latest["period"] > actual.index[-1]) & (latest["period"] < _fy_period(latest_budget))
    ].sort_values("period")
    if candidates.empty:
        return None
    row = candidates.iloc[0]
    return pd.Series(
        [actual.iloc[-1], row["value"]],
        index=pd.PeriodIndex([actual.index[-1], row["period"]], freq="Y"),
        name="Estimated outcome (latest Budget)",
    )


def _build_forward_series(bp1: pd.DataFrame, *, start_before_budget_year: bool = False) -> list[pd.Series]:
    """One Series per BP1 — its values from the budget year onwards.

    That is the budget year + 3 forward projection years. With
    `start_before_budget_year`, each line also starts one year earlier, at the
    BP1's estimate of the year it was delivered in — for tables (such as BP1's
    revenue by head) that only publish that year and the budget year.
    """
    out: list[pd.Series] = []
    for budget_year in sorted(bp1["budget_year"].unique()):
        group = bp1[bp1["budget_year"] == budget_year]
        bg_period = _fy_period(budget_year) - (1 if start_before_budget_year else 0)
        forward = group[group["period"] >= bg_period].sort_values("period")
        if len(forward) < _MIN_LINE_POINTS:
            continue
        out.append(
            pd.Series(
                forward["value"].values,
                index=pd.PeriodIndex(forward["period"].values, freq="Y"),
                name=f"_fwd_{budget_year}",
            )
        )
    return out


def _plot_layers(
    actual: pd.Series | None,
    bridge: pd.Series | None,
    forwards: list[pd.Series],
    forward_label: str,
) -> Axes | None:
    """Layer actual, bridge and forward-estimate lines onto one axes; None if nothing drawn."""
    # `ax=None` on the first call creates the axes; subsequent calls layer onto it.
    ax = None
    if actual is not None:
        ax = mg.line_plot(
            actual,
            ax=ax,
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

    # Only the first forward line is labelled, so the legend shows one entry.
    for i, series in enumerate(forwards):
        labelled = series.rename(forward_label) if i == 0 else series
        ax = mg.line_plot(
            labelled,
            ax=ax,
            color=["darkorange"],
            width=1.0,
            alpha=0.7,
            annotate=False,
            label_series=[i == 0],
        )
    return ax


def plot_aggregate(
    line_item: str,
    measure: str = "$b",
    *,
    title: str | None = None,
    ylabel: str | None = None,
    lfooter: str = "Australia. General government sector.",
    rfooter: str = "Source: Treasury BP1 + Final Budget Outcome",
    lheader: str | None = None,
    rheader: str | None = None,
    start_before_budget_year: bool = False,
) -> None:
    """Build and save the standard 'actuals vs forward estimates' chart for one aggregate.

    Args:
        line_item: line item name as it appears in the parquet, e.g. "Expenses",
            "Revenue", "Receipts", "Underlying cash balance".
        measure: "$b" (default) or "Per cent of GDP".
        title: chart title (also drives the filename). Defaults to
            "Australian Government {line_item}".
        ylabel: y-axis label. Defaults based on `measure`.
        lfooter: left footer, passed through to `finalise_plot`.
        rfooter: right footer, passed through to `finalise_plot`.
        lheader: optional left header, passed through to `finalise_plot`.
        rheader: optional right header, passed through to `finalise_plot`.
        start_before_budget_year: start each BP1 line at its estimate of the
            year it was delivered in, and label the lines "Budget estimates"
            (they are no longer purely forward estimates).

    Saves to `charts/{slugified-title}.png`.

    """
    fbo, bp1 = _load_filtered(line_item, measure)
    if fbo.empty and bp1.empty:
        raise ValueError(f"No data for line_item={line_item!r}, measure={measure!r} in either parquet.")

    actual = _build_actual(fbo)
    bridge = _build_bridge(actual, bp1)
    forwards = _build_forward_series(bp1, start_before_budget_year=start_before_budget_year)
    forward_label = "Budget estimates" if start_before_budget_year else "Forward estimates"

    if title is None:
        title = f"Australian Government {line_item}"
    if ylabel is None:
        ylabel = "$ billion" if measure == "$b" else measure

    mg.set_chart_dir(str(ROOT / "charts"))

    ax = _plot_layers(actual, bridge, forwards, forward_label)
    if ax is None:
        raise ValueError(f"No data available to plot for {line_item!r}")

    finalise_kwargs: dict = {
        "title": title,
        "ylabel": ylabel,
        "xlabel": "Financial year beginning July",
        "rfooter": rfooter,
        "lfooter": lfooter,
        "legend": True,
        "y0": True,  # y=0 reference line when data crosses zero (UCB, fiscal balance)
        "show": False,
    }
    if lheader is not None:
        finalise_kwargs["lheader"] = lheader
    if rheader is not None:
        finalise_kwargs["rheader"] = rheader

    mg.finalise_plot(ax, **finalise_kwargs)
