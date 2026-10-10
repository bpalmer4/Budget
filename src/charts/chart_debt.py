"""Chart Australian Government Net debt and Gross debt: FBO actuals + BP1 forwards.

Net debt: 15 years of actuals. Gross debt: 4 years of actuals (Treasury added
it as a headline aggregate from 2021-22 onwards). BP1 forecast coverage for
both starts at the 2020-21 BP1.

Run:
    uv run python -m src.charts.chart_debt
"""

from src.charts.aggregate import plot_aggregate


def main() -> None:
    """Chart FBO outcomes against each BP1's forward estimates for Net debt, Gross debt and Net interest payments."""
    plot_aggregate(
        "Net debt",
        lfooter=("Australia. General government sector. Net debt = issued bonds less liquid financial assets."),
        rfooter="Source: Treasury BP1 + FBO.",
        rheader=("Bonds priced at market value (yield-sensitive). Future Fund not deducted."),
    )
    plot_aggregate("Gross debt")
    plot_aggregate(
        "Net interest payments",
        lfooter=(
            "Australia. General government sector. Net interest payments = interest paid less interest received."
        ),
        rfooter="Source: Treasury BP1 + FBO.",
    )


if __name__ == "__main__":
    main()
