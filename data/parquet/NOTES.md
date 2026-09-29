# Extractors

One file per source-doc type. Each writes its own parquet under `data/parquet/`.

| Script                     | Output                  | Captures                                                  |
|----------------------------|-------------------------|-----------------------------------------------------------|
| `extract_bp1.py`           | `bp1_estimates.parquet` | BP1 GFS aggregates (Receipts, Payments, UCB, Revenue, …)  |
| `extract_bp1_functions.py` | `bp1_functions.parquet` | BP1 14-function expenses                                  |
| `extract_bp1_debt.py`      | `bp1_debt.parquet`      | BP1 Net debt + Gross debt forecasts                       |
| `extract_bp1_hcb.py`       | `bp1_hcb.parquet`       | BP1 Headline cash balance (cash flow statement — dropped from the aggregates table from 2022-23) |
| `extract_bp1_economic.py`  | `bp1_economic.parquet`  | BP1 Statement 2 economic forecasts (Real GDP, CPI, WPI, Unemployment rate, Terms of trade, …) |
| `extract_bp1_overview.py`  | `bp1_overview.parquet`  | BP1 Statement 1 Table 1.1: Major Economic Parameters — extended forecast horizon for the 6 major series |
| `extract_bp3_nom.py`       | `bp3_nom.parquet`       | BP3 Appendix A Net overseas migration — 17 budgets, longer history than BP1 |
| `extract_bp1_revenue.py`   | `bp1_revenue.parquet`   | BP1 accrual revenue by head (~35 heads) — reconciliation tables only, so the delivery year + budget year per BP1 |
| `extract_fbo.py`           | `fbo_outcomes.parquet`  | FBO GFS aggregates outcomes                               |
| `extract_fbo_revenue.py`   | `fbo_revenue.parquet`   | FBO accrual revenue outcomes by head (~35 heads)          |
| `extract_fbo_functions.py` | `fbo_functions.parquet` | FBO 14-function outcomes                                  |
| `extract_fbo_debt.py`      | `fbo_debt.parquet`      | FBO Net debt + Gross debt outcomes                        |
| `extract_fbo_hcb.py`       | `fbo_hcb.parquet`       | FBO Headline cash balance (Part 2 cash flow statement — dropped from the Part 1 aggregates table from 2021-22) |

Run any of them with:

```bash
uv run python -m src.extract.<name>
```

All output the same schema (long format):
`(budget_year?, fiscal_year, line_item, measure, value)` — `budget_year` is
present in the BP1/BP3 parquets and omitted in the FBO ones.

The chart helpers in `src/charts/aggregate.py` and `src/charts/variance.py`
read from every parquet in this set transparently, so any `line_item` from any
source becomes plottable via `plot_aggregate("<line item>")` or
`plot_variance("<line item>")` with no chart-side code changes.

## Parsers

Each extractor has one or more parser modules under `src/data/`:

| Extractor              | Parser(s)                          |
|------------------------|------------------------------------|
| `extract_bp1.py`            | `bp1_pdf.py`                       |
| `extract_bp1_functions.py`  | `bp1_function.py`                  |
| `extract_bp1_debt.py`       | `bp1_debt.py` (uses PyMuPDF outline navigation for speed) |
| `extract_bp1_hcb.py`        | `bp1_hcb.py` (PyMuPDF page pre-scan for speed)            |
| `extract_bp1_economic.py`   | `bp1_economic.py` (PyMuPDF outline; Treasury fractions like `1 3/4` → 1.75) |
| `extract_bp3_nom.py`        | `bp3_nom.py` (BP3 Appendix A NOM table; handles two column-label formats across years) |
| `extract_bp1_revenue.py`    | `bp1_revenue.py`, `revenue_heads.py` (shared label map + sum check) |
| `extract_fbo.py`            | `fbo_docx.py`, `fbo_pdf.py`        |
| `extract_fbo_revenue.py`    | `fbo_revenue.py`, `revenue_heads.py` |
| `extract_fbo_functions.py`  | `fbo_function.py`                  |
| `extract_fbo_debt.py`       | `fbo_debt.py`                      |
| `extract_fbo_hcb.py`        | `fbo_hcb.py`                       |
