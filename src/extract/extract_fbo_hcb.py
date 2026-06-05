"""Extract FBO Headline cash balance outcomes for every DOCX year.

Writes `data/parquet/fbo_hcb.parquet`. FBOs from 2021-22 onwards dropped
Headline cash balance from the Part 1 aggregates table, so this fills the gap
from the Part 2 cash flow statement. Pre-2019-20 (PDF-only) years are already
covered by `fbo_outcomes.parquet`.

Run:
    uv run python -m src.extract.extract_fbo_hcb
"""

from __future__ import annotations

import sys

import pandas as pd

from src.data.fbo_hcb import load_fbo_hcb
from src.utilities.paths import OUTCOME_DIR, PARQUET_DIR


def _discover_years() -> list[str]:
    if not OUTCOME_DIR.is_dir():
        return []
    return sorted(
        d.name for d in OUTCOME_DIR.iterdir()
        if d.is_dir() and (d / "fbo_02_part_2.docx").exists()
    )


def main() -> int:
    years = _discover_years()
    if not years:
        print(f"No FBO Part 2 DOCX under {OUTCOME_DIR}", file=sys.stderr)
        return 1

    print(f"Extracting FBO headline cash balance for {len(years)} year(s)\n")
    frames: list[pd.DataFrame] = []
    for year in years:
        try:
            df = load_fbo_hcb(year)
        except Exception as exc:  # noqa: BLE001
            print(f"  {year}: FAILED  ({type(exc).__name__}: {exc})",
                  file=sys.stderr)
            continue
        value = f"{df['value'].iloc[0]:.1f}" if not df.empty else "(missing)"
        print(f"  {year}: {value}")
        frames.append(df)

    if not frames:
        print("\nNo data extracted.", file=sys.stderr)
        return 1

    combined = pd.concat(frames, ignore_index=True)
    PARQUET_DIR.mkdir(exist_ok=True)
    out = PARQUET_DIR / "fbo_hcb.parquet"
    combined.to_parquet(out, index=False)
    print(f"\nWrote {len(combined)} rows to {out.relative_to(PARQUET_DIR.parent.parent)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
