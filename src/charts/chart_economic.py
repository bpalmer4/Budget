"""Chart the BP1 economic forecasts vs ABS actuals, plus the BP3-sourced NOM.

One PNG per BP1-tracked series (Real GDP, Nominal GDP, CPI, WPI, Employment,
Unemployment rate, Net overseas migration), followed by a separate BP3-sourced
NOM chart drawing on the longer BP3 forecast history.

Run:
    uv run python -m src.charts.chart_economic
"""

from src.charts.abs_history import SUPPORTED_LINE_ITEMS
from src.charts.chart_nom_bp3 import main as render_nom_bp3
from src.charts.economic import plot_economic_forecast


def main() -> None:
    """Chart each supported economic forecast against ABS history, then the BP3 NOM chart.

    A failure is reported and the loop carries on.
    """
    for line_item in SUPPORTED_LINE_ITEMS:
        try:
            plot_economic_forecast(line_item)
            print(f"  ok    {line_item}")
        except Exception as exc:  # noqa: BLE001 - surface any failures, keep looping
            print(f"  FAIL  {line_item}: {type(exc).__name__}: {exc}")
    render_nom_bp3()


if __name__ == "__main__":
    main()
