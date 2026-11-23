"""Extract the MYEFO underlying cash balance reconciliation for every MYEFO on disk.

Writes `data/parquet/myefo_reconciliation.parquet`.

Run:
    uv run python -m src.extract.extract_myefo_reconciliation
"""

from __future__ import annotations

import sys

import pandas as pd

from src.data.myefo_reconciliation import load_myefo_reconciliation
from src.utilities.paths import MYEFO_DIR, PARQUET_DIR


def _discover_myefos() -> list[str]:
    if not MYEFO_DIR.is_dir():
        return []
    return sorted(d.name for d in MYEFO_DIR.iterdir() if d.is_dir() and (d / "myefo.pdf").exists())


def main() -> int:
    """Extract every MYEFO's reconciliation into myefo_reconciliation.parquet.

    Return 1 if nothing could be extracted.
    """
    years = _discover_myefos()
    if not years:
        print(f"No MYEFO PDFs found under {MYEFO_DIR}", file=sys.stderr)
        return 1

    frames: list[pd.DataFrame] = []
    for year in years:
        try:
            df = load_myefo_reconciliation(year)
        except Exception as exc:  # noqa: BLE001 - top-level extract, surface every failure
            print(f"  {year}: FAILED  ({type(exc).__name__}: {exc})", file=sys.stderr)
            continue
        print(f"  {year}: {len(df):4d} rows  (stages: {', '.join(df['stage'].unique())})")
        frames.append(df)

    if not frames:
        print("\nNo data extracted.", file=sys.stderr)
        return 1

    combined = pd.concat(frames, ignore_index=True)
    PARQUET_DIR.mkdir(exist_ok=True)
    out = PARQUET_DIR / "myefo_reconciliation.parquet"
    combined.to_parquet(out, index=False)
    print(f"\nWrote {len(combined)} rows to {out.relative_to(PARQUET_DIR.parent.parent)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
