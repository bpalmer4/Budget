"""Chart Australian Government Headline Cash Balance: FBO actuals + forward estimates from every BP1.

The headline cash balance is the underlying cash balance plus net cash flows
from investments in financial assets for policy purposes (student loans, NBN,
CEFC, Housing Australia, ...) — the all-inclusive cash measure.

Run:
    uv run python -m src.charts.chart_hcb
"""

from src.charts.aggregate import plot_aggregate


def main() -> None:
    """Chart FBO outcomes against each BP1's forward estimates for the Headline cash balance."""
    plot_aggregate(
        "Headline cash balance",
        title="Australian Government Headline Cash Balance",
    )


if __name__ == "__main__":
    main()
