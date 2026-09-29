"""Extract FBO accrual revenue outcomes by head for every available year.

DOCX path (2019-20 onwards): `src.data.fbo_revenue.load_fbo_revenue_docx`.
PDF path (pre-2019-20):       `src.data.fbo_revenue.load_fbo_revenue_pdf`.

Each year is checked twice before it is kept:
- the heads (leaves added, refunds subtracted) must sum to its Total revenue;
- that Total revenue must match the Revenue aggregate in `fbo_outcomes.parquet`,
  which comes from a different FBO table.
"Total revenue" itself is then dropped — it duplicates the Revenue aggregate.

Run:
    uv run python -m src.extract.extract_fbo_revenue
"""

from __future__ import annotations

import sys

import pandas as pd

from src.data import fbo_revenue
from src.data.revenue_heads import TOTAL_REVENUE, additive_sum
from src.utilities.paths import OUTCOME_DIR, PARQUET_DIR

SUM_TOLERANCE_B = 0.05  # heads vs Total revenue, $b (rounding of ~30 $m cells)
AGGREGATE_TOLERANCE_B = 0.06  # vs the aggregate, published to $0.1b


def _discover_years() -> list[tuple[str, str]]:
    if not OUTCOME_DIR.is_dir():
        return []
    out: list[tuple[str, str]] = []
    for d in sorted(OUTCOME_DIR.iterdir()):
        if not d.is_dir():
            continue
        if (d / "fbo_01_part_1.docx").exists():
            out.append((d.name, "docx"))
        elif (d / "fbo.pdf").exists():
            out.append((d.name, "pdf"))
    return out


def _revenue_aggregate() -> pd.Series:
    fbo = pd.read_parquet(PARQUET_DIR / "fbo_outcomes.parquet")
    fbo = fbo[(fbo["line_item"] == "Revenue") & (fbo["measure"] == "$b")]
    return fbo.set_index("fiscal_year")["value"]


def _check(df: pd.DataFrame, fiscal_year: str, aggregate: pd.Series) -> list[str]:
    values = dict(zip(df["line_item"], df["value"], strict=True))
    total = values.get(TOTAL_REVENUE)
    if total is None:
        return ["no Total revenue row"]
    problems: list[str] = []
    heads = additive_sum(values)
    if abs(heads - total) > SUM_TOLERANCE_B:
        problems.append(f"heads sum {heads:.3f} ≠ Total revenue {total:.3f}")
    agg = aggregate.get(fiscal_year)
    if agg is not None and abs(agg - total) > AGGREGATE_TOLERANCE_B:
        problems.append(f"Total revenue {total:.3f} ≠ Revenue aggregate {agg:.1f}")
    return problems


def main() -> int:
    """Extract, check and write `fbo_revenue.parquet`."""
    targets = _discover_years()
    if not targets:
        print(f"No FBO files found under {OUTCOME_DIR}", file=sys.stderr)
        return 1

    print(f"Extracting FBO accrual revenue by head for {len(targets)} year(s)\n")
    aggregate = _revenue_aggregate()

    frames: list[pd.DataFrame] = []
    for year, source in targets:
        loader = (fbo_revenue.load_fbo_revenue_docx if source == "docx"
                  else fbo_revenue.load_fbo_revenue_pdf)
        try:
            df = loader(year)
        except Exception as exc:  # noqa: BLE001 - report and keep going
            print(f"  {year} ({source}): FAILED  ({type(exc).__name__}: {exc})", file=sys.stderr)
            continue
        problems = _check(df, year, aggregate)
        status = "ok" if not problems else "CHECK FAILED: " + "; ".join(problems)
        print(f"  {year} ({source}): {len(df):2d} rows  {status}")
        frames.append(df[df["line_item"] != TOTAL_REVENUE])

    if not frames:
        print("\nNo data extracted.", file=sys.stderr)
        return 1

    combined = pd.concat(frames, ignore_index=True)
    PARQUET_DIR.mkdir(exist_ok=True)
    out = PARQUET_DIR / "fbo_revenue.parquet"
    combined.to_parquet(out, index=False)

    print(f"\nWrote {len(combined)} rows to {out.relative_to(PARQUET_DIR.parent.parent)}")
    print(f"Years covered:  {', '.join(sorted(combined['fiscal_year'].unique()))}")
    print(f"Unique heads:   {combined['line_item'].nunique()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
