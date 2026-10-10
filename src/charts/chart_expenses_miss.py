"""1/2/3-year-ahead forecast miss for Australian Government Expenses.

Run:
    uv run python -m src.charts.chart_expenses_miss
"""

from src.charts.variance import plot_variance


def main() -> None:
    """Chart the 1-, 2- and 3-year-ahead forecast miss for Expenses."""
    plot_variance("Expenses")


if __name__ == "__main__":
    main()
