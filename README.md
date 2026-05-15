# Budget

Track Australian Federal Budget forward estimates against Final Budget Outcomes (FBO). Compares Treasury's published projections — fiscal aggregates, headline expense functions, and major economic parameters — against the actuals that followed.

Two-stage pipeline: parse Treasury Budget Paper PDFs/DOCX into Parquet (`src/extract/`), then render PNG charts from the Parquet (`src/charts/`).

```bash
uv sync
uv run python -m src.extract.extract_bp1
uv run python -m src.extract.extract_fbo
uv run python -m src.charts.chart_economic
```

See [data/parquet/NOTES.md](data/parquet/NOTES.md) for the full list of extractors and the Parquet they produce.

Source documents aren't shipped with the repo; they're freely available from `archive.budget.gov.au` and `budget.gov.au`. See [data/DATA_POLICY.md](data/DATA_POLICY.md) for the directory layout and per-year quirks.
