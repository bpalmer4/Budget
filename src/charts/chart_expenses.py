"""Chart Australian Government Expenses: FBO actuals + forward estimates from every BP1.

Run:
    uv run python -m src.charts.chart_expenses
"""

from src.charts.aggregate import plot_aggregate


def main() -> None:
    """Chart FBO outcomes against each BP1's forward estimates for Expenses."""
    plot_aggregate("Expenses")


if __name__ == "__main__":
    main()
