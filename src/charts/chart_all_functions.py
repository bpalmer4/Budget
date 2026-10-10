"""Chart all 14 GFS expenses-by-function categories: FBO actuals + BP1 forwards.

One PNG per function, written to `charts/`.

Run:
    uv run python -m src.charts.chart_all_functions
"""

from src.charts.aggregate import plot_aggregate
from src.data.fbo_function import KNOWN_FUNCTIONS


def main() -> None:
    """Plot every function's expenses, reporting failures without stopping."""
    for function in KNOWN_FUNCTIONS:
        try:
            plot_aggregate(function, title=f"Australian Government Expenses: {function}")
            print(f"  ok    {function}")
        except Exception as exc:  # noqa: BLE001 - surface any failures, keep looping
            print(f"  FAIL  {function}: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
