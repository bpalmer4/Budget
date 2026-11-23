"""Latest MYEFO: what moved the underlying cash balance since the Budget.

One stacked bar per fiscal year, from MYEFO's own reconciliation table. Each
segment is its effect on the underlying cash balance, so the segments sum to
the MYEFO − Budget revision in `chart_myefo_revisions.py`:

- Earlier stages (Budget → PEFO in election years), policy and parameters combined.
- Receipts: policy decisions / parameter and other variations.
- Payments: policy decisions / parameter and other variations — negated,
  since more spending lowers the balance.

As a check, the stack total is compared with MYEFO − Budget from the
aggregates parquets; the result is printed.

Run:
    uv run python -m src.charts.chart_myefo_drivers
"""

import mgplot as mg
import pandas as pd

from src.utilities.paths import PARQUET_DIR, ROOT

_UCB = "Underlying cash balance"
_CHECK_TOLERANCE_B = 0.1  # table is in $m; aggregates are rounded to $0.1b
_FINAL_STAGE_SUFFIX = "MYEFO"
_SIGN = {"Receipts": 1.0, "Payments": -1.0, _UCB: 1.0}
_NET_EDGE = "black"
_NET_DOT_SIZE = 60  # points², matplotlib scatter size
_SHORT = {"Policy decisions": "policy decisions", "Parameter and other variations": "parameter variations"}


def _segments(recon: pd.DataFrame) -> pd.DataFrame:
    """Effect on the balance ($b): rows are fiscal years, columns are segments."""
    df = recon.assign(effect=recon["value"] * recon["line_item"].map(_SIGN))
    final = df["stage"].str.endswith(_FINAL_STAGE_SUFFIX)

    earlier = df[~final]
    parts: list[pd.Series] = []
    for stage, group in earlier.groupby("stage", sort=False):
        parts.append(group.groupby("fiscal_year")["effect"].sum().rename(str(stage)))
    for (line_item, component), group in df[final].groupby(["line_item", "component"], sort=False):
        label = f"{line_item}: {_SHORT.get(str(component), str(component))}"
        parts.append(group.groupby("fiscal_year")["effect"].sum().rename(label))
    out = pd.concat(parts, axis=1)
    # Earlier stages first, then Receipts before Payments.
    split = sorted((c for c in out.columns if ":" in c), key=lambda c: (not c.startswith("Receipts"), c))
    order = [c for c in out.columns if ":" not in c] + split
    return out.loc[:, order]


def _check(segments: pd.DataFrame, budget_year: str) -> None:
    def ucb(name: str) -> pd.Series:
        df = pd.read_parquet(PARQUET_DIR / name)
        sel = df[(df["budget_year"] == budget_year) & (df["line_item"] == _UCB) & (df["measure"] == "$b")]
        return sel.set_index("fiscal_year")["value"]

    revision = (ucb("myefo_estimates.parquet") - ucb("bp1_estimates.parquet")).dropna()
    for fy, total in segments.sum(axis=1).items():
        if not isinstance(fy, str):
            raise TypeError(f"Fiscal year index should be str, got {fy!r}")
        gap = total - revision[fy]
        status = "ok" if abs(gap) <= _CHECK_TOLERANCE_B else "MISMATCH"
        print(f"  {fy}: segments {total:+.2f} vs UCB revision {revision[fy]:+.1f} $b  {status}")


def main() -> None:
    """Draw the policy-vs-parameter stacked bar chart for the latest MYEFO."""
    recon = pd.read_parquet(PARQUET_DIR / "myefo_reconciliation.parquet")
    budget_year = max(recon["budget_year"])
    segments = _segments(recon[recon["budget_year"] == budget_year])
    print(f"Latest MYEFO: {budget_year}\n{segments.round(2).to_string()}")
    _check(segments, budget_year)

    mg.set_chart_dir(str(ROOT / "charts"))
    ax = mg.bar_plot(segments, stacked=True)
    totals = segments.sum(axis=1)
    # Net effect marker: raw matplotlib (agreed) — mgplot can't draw a per-bar tick.
    # Bar centres and width come from the drawn bars, one per fiscal year.
    bars = ax.containers[0]
    centres = [b.get_x() + b.get_width() / 2 for b in bars]
    half = bars[0].get_width() / 4  # line spans the middle half of the bar
    ax.hlines(
        totals.to_numpy(), [c - half for c in centres], [c + half for c in centres], color=_NET_EDGE, lw=2, zorder=4
    )
    ax.scatter(
        centres, totals.to_numpy(), s=_NET_DOT_SIZE, color="white", edgecolor=_NET_EDGE, zorder=5, label="Net effect"
    )
    title = f"{budget_year} MYEFO: what moved the underlying cash balance"
    mg.finalise_plot(
        ax,
        title=title,
        filename=f"Australian Government {title}",
        ylabel="Effect on the balance ($ billion)",
        xlabel=None,
        y0=True,
        lheader="Up: improves the balance. Higher payments show as down.",
        rheader="Net: " + ", ".join(f"{fy} {v:+.1f}" for fy, v in totals.items()),
        lfooter="Australia. General government sector. Cash. Changes since the Budget.",
        rfooter=f"Source: Treasury {budget_year} MYEFO Table 3.2",
        legend=True,
        show=False,
    )


if __name__ == "__main__":
    main()
