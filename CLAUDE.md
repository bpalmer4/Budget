# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

The Budget project tracks Australian Federal Budget forward estimates against Final Budget Outcomes (FBO), in aggregate and against headline expenditure categories. Source documents are the Treasury Budget Papers (Paper No. 1 in particular — the "table of truth") and the Final Budget Outcome statements published the following September.

Data extraction works from **per-statement DOCX files** rather than PDFs, because the DOCX preserves the underlying budget tables as real Word tables (`<w:tbl>` XML elements). PDFs are kept as the human-readable reference but are not the parse target.

See `data/DATA_POLICY.md` for the data layout, file-naming convention, year-specific decisions (2022-23 → October Labor budget; 2020-21 → October delivery), and FBO availability notes.

## Project Structure

All Python lives under `src/`. Library code (parsers, helpers) and entry-point scripts (extract, chart) share the same tree so imports stay simple. The scripts *are* the project.

```
src/
├── data/                         # parsers: DOCX/PDF → DataFrame (library)
│   ├── bp1.py
│   ├── fbo_docx.py
│   └── fbo_pdf.py                # legacy pre-2019-20 FBOs
├── utilities/                    # shared helpers (paths, year ranges, table filters)
├── extract/                      # ETL entry points: source docs → data/parquet/
│   ├── extract_bp1.py
│   └── extract_fbo.py
└── charts/                       # chart entry points: data/parquet/ → charts/
    └── chart_*.py

data/
├── Budget/{YYYY-YY}/             # BP1 PDF (all 17 budgets, 2010-11 → 2026-27);
│                                 # BP1 DOCX only for 2022-23, 2024-25, 2025-26, 2026-27
│                                 # (older budgets don't publish DOCX — see DATA_POLICY.md).
├── MYEFO/                        # (future) Mid-Year Economic and Fiscal Outlook
├── Outcome/{YYYY-YY}/            # FBO PDF (all 15 years) + DOCX parts (2019-20 onwards)
└── parquet/                      # extracted Parquet — chart scripts read from here

charts/                           # generated PNG output
output/                           # other derived artefacts (CSV exports, etc.)
```

Pure Python — no Jupyter notebooks in this project. `src/` is a PEP 420 namespace package (no top-level `__init__.py`); subpackages have their own `__init__.py`.

## Workflow

Two-stage pipeline: **extract once, chart many times.**

1. **Extract** (`scripts/extract/*.py`) — parse the source DOCX/PDFs, build tidy DataFrames, write Parquet to `data/parquet/`. Run when source docs change or parsers are updated, not every chart run.
2. **Chart** (`scripts/charts/*.py`) — `pd.read_parquet(...)`, filter, plot. Zero parsing, zero `python-docx` dependency at chart time.

```bash
# Re-extract everything
uv run python -m src.extract.extract_bp1
uv run python -m src.extract.extract_fbo

# Produce a chart
uv run python -m src.charts.chart_aggregate_variance
```

**Parquet schema convention** — tidy/long format: `[budget_year, source_doc, statement_no, line_item, fiscal_year, value, unit]`. One row per (budget × line item × fiscal year). Pivot to wide format inside chart scripts when needed.

Source documents under `data/Budget/`, `data/Outcome/` etc. are immutable inputs — never write to them from code. Extracted Parquet under `data/parquet/` is derived and regenerable.

## Development Setup

- Python environment managed with `uv`, virtual env in `.venv/`
- Python `>=3.14` (matches the rest of Bryan's Python projects)

```bash
uv sync                   # Install dependencies
./uv-upgrade.sh           # Upgrade dependencies (added when first needed)
```

## Key Dependencies

- **python-docx**: Parse `<w:tbl>` elements from BP1/FBO DOCX. Primary data-extraction library.
- **pandas / numpy**: Data manipulation.
- **pyarrow**: Parquet for cached/derived DataFrames.
- **mgplot**: Plotting wrapper over matplotlib (house style, footers, `finalise_plot`). Use raw matplotlib only when mgplot genuinely can't do the job, and only after agreeing with the user first. See `## Plotting`.

## Coding practice

- Think Before Coding: Don't assume. Don't hide confusion. Surface tradeoffs.
- Simplicity First: Minimum code that solves the problem. Nothing speculative.
- Surgical Changes: Touch only what you must. Clean up only your own mess.
- Goal-Driven Execution: Define success criteria. Loop until verified.

## Code Style

- Type hints throughout (PEP 484). `from __future__ import annotations` where useful.
- Ruff for linting (config in `pyproject.toml` once initialised).
- Wrap logic in functions; module-level code limited to imports, constants, and CLI entry points.
- No magic numbers — named constants or function parameters.
- Use `.loc[]` over `.at[]` (mypy preference).

## Data extraction conventions

When writing parsers in `src/data/`:

- **Locate documents by path, not lookup table.** Every year follows the same path layout (e.g. `data/Budget/{year}/bp1.pdf`, `data/Outcome/{year}/fbo_01_part_1.docx`), so a parser takes a year (and statement/part) and constructs the path directly.
- **Prefer DOCX over PDF when DOCX is genuinely available — but verify, don't assume.** DOCX preserves real Word tables (`<w:tbl>`) and is much easier to parse, but it's only published for a subset of years:
  - **FBO DOCX:** all years from 2019-20 onwards (verified hash-unique per year).
  - **BP1 DOCX:** only 2022-23, 2024-25, 2025-26, 2026-27. For other years the budget.gov.au server silently returns the *current* budget's DOCX, so DOCX URLs for older years are misleading. **For BP1, parse from PDF uniformly across all 17 budgets** — keeps the parser path consistent and avoids the trap.
- **Filter layout tables.** Some `<w:tbl>` elements (DOCX) or pdfplumber-detected tables are styled boxes or chart layout grids rather than data tables. Detect heuristically (e.g. content doesn't contain expected aggregate labels) and skip rather than assuming every table is data.
- **Preserve the year(s) as columns** in every returned DataFrame so multi-year frames concatenate cleanly. For BP1: keep both `budget_year` (which BP1 published the estimate) and `fiscal_year` (which year the estimate is *for*). For FBO: just `fiscal_year` (the year of the actual).

## Plotting

Use `mgplot`. Raw matplotlib only when mgplot genuinely can't do the job, and only after agreeing the approach with the user. Existing chart scripts in `src/charts/` are the reference for house conventions:

- `import mgplot as mg`.
- `mg.set_chart_dir(str(ROOT / "charts"))` once near the top of the script.
- Build each layer as a `pd.Series`; the series `.name` becomes its legend label (prefix with `_` to suppress).
- Layer by threading `ax` through successive `mg.line_plot(..., ax=ax, ...)` calls; the first call passes `ax=None`.
- Close with `mg.finalise_plot(ax, title=..., ylabel=..., xlabel=..., rfooter=..., lfooter=..., legend=True, show=False)` — this writes the PNG.

## Git

- **Reading is fine** — `git status`, `git log`, `git diff`, `git show`, `git blame` etc. are useful for checking against past versions.
- **No commits and no pushes.** User manages all version control manually. Never run `git commit`, `git push`, `git add` followed by a commit, or any other mutating git operation.

## Interaction

- Never provide clickable suggested next steps (user hits them accidentally). Text suggestions in responses are fine.
- For decisions about data scope or year coverage, defer to `data/DATA_POLICY.md` rather than re-deriving them in code or in conversation.
