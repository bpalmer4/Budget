"""Chart Australian Government Revenue: FBO actuals + forward estimates from every BP1.

Run:
    uv run python -m src.charts.chart_revenue
"""

from src.charts.aggregate import plot_aggregate


def main() -> None:
    """Chart FBO outcomes against each BP1's forward estimates for Revenue."""
    plot_aggregate("Revenue")


if __name__ == "__main__":
    main()
