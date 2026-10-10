"""Chart Australian Government Underlying Cash Balance: FBO actuals + forward estimates from every BP1.

Run:
    uv run python -m src.charts.chart_ucb
"""

from src.charts.aggregate import plot_aggregate


def main() -> None:
    """Chart FBO outcomes against each BP1's forward estimates for the Underlying cash balance."""
    plot_aggregate(
        "Underlying cash balance",
        title="Australian Government Underlying Cash Balance",
    )


if __name__ == "__main__":
    main()
