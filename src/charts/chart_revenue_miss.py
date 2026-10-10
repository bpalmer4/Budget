"""1/2/3-year-ahead forecast miss for Australian Government Revenue.

Run:
    uv run python -m src.charts.chart_revenue_miss
"""

from src.charts.variance import plot_variance


def main() -> None:
    """Chart the 1-, 2- and 3-year-ahead forecast miss for Revenue."""
    plot_variance("Revenue")


if __name__ == "__main__":
    main()
