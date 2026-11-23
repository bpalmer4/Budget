"""Extract MYEFO aggregates for every MYEFO on disk and write Parquet.

Scans `data/MYEFO/` for fiscal-year directories with a `myefo.pdf`, parses the
cash and accrual aggregates tables from each, and writes
`data/parquet/myefo_estimates.parquet`.

Run:
    uv run python -m src.extract.extract_myefo
"""

from __future__ import annotations

import sys

import pandas as pd

from src.data.myefo_aggregates import load_myefo_estimates
from src.utilities.paths import MYEFO_DIR, PARQUET_DIR


def _discover_myefos() -> list[str]:
    if not MYEFO_DIR.is_dir():
        return []
    return sorted(d.name for d in MYEFO_DIR.iterdir() if d.is_dir() and (d / "myefo.pdf").exists())


def main() -> int:
    """Extract the aggregates from every MYEFO into myefo_estimates.parquet.

    Return 1 if nothing could be extracted.
    """
    years = _discover_myefos()
    if not years:
        print(f"No MYEFO PDFs found under {MYEFO_DIR}", file=sys.stderr)
        return 1

    print(f"Extracting MYEFO aggregates for {len(years)} year(s): {', '.join(years)}\n")

    frames: list[pd.DataFrame] = []
    for year in years:
        try:
            df = load_myefo_estimates(year)
        except Exception as exc:  # noqa: BLE001 - top-level extract, surface every failure
            print(f"  {year}: FAILED  ({type(exc).__name__}: {exc})", file=sys.stderr)
            continue
        n_fy = df["fiscal_year"].nunique()
        n_li = df["line_item"].nunique()
        print(f"  {year}: {len(df):4d} rows  ({n_li:2d} line items × {n_fy} fiscal years)")
        frames.append(df)

    if not frames:
        print("\nNo data extracted.", file=sys.stderr)
        return 1

    combined = pd.concat(frames, ignore_index=True)
    PARQUET_DIR.mkdir(exist_ok=True)
    out = PARQUET_DIR / "myefo_estimates.parquet"
    combined.to_parquet(out, index=False)
    print(f"\nWrote {len(combined)} rows to {out.relative_to(PARQUET_DIR.parent.parent)}")
    print(f"Line items: {sorted(combined['line_item'].unique())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
