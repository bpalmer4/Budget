"""Chart BP3 NOM forecasts vs ABS actuals.

Mirrors the BP1 NOM chart in `chart_economic.py`, but pulls forecast
trajectories from `bp3_nom.parquet` (17 BP3s, 2010-11 → 2026-27, Appendix A)
instead of `bp1_economic.parquet` (5 BP1s, 2022-23 → 2026-27, Statement 2).

Run:
    uv run python -m src.charts.chart_nom_bp3
"""

from __future__ import annotations

from src.charts.economic import plot_economic_forecast


def render() -> None:
    """Chart every BP3 Net overseas migration forecast against ABS actuals."""
    plot_economic_forecast(
        "Net overseas migration",
        sources=("bp3_nom.parquet",),
        title="BP3 forecasts vs ABS actuals: Net overseas migration",
        rfooter="Sources: ABS; Treasury BP3.",
    )


def main() -> None:
    """Draw the chart, reporting a failure instead of raising it."""
    try:
        render()
        print("  ok    Net overseas migration (BP3)")
    except Exception as exc:  # noqa: BLE001
        print(f"  FAIL  Net overseas migration (BP3): {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
