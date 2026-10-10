"""Chart Australian Government Defence expenses: FBO actuals + BP1 forward estimates.

Run:
    uv run python -m src.charts.chart_defence
"""

from src.charts.aggregate import plot_aggregate


def main() -> None:
    """Plot Defence expenses."""
    plot_aggregate("Defence", title="Australian Government Expenses: Defence")


if __name__ == "__main__":
    main()
