"""Extract FBO Net debt and Gross debt outcomes for every available year.

Writes `data/parquet/fbo_debt.parquet` so the chart functions can pick it up
alongside the existing FBO outcome data.

Run:
    uv run python -m src.extract.extract_fbo_debt
"""

from __future__ import annotations

import sys

import pandas as pd

from src.data import fbo_debt
from src.utilities.paths import OUTCOME_DIR, PARQUET_DIR


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


def main() -> int:
    targets = _discover_years()
    if not targets:
        print(f"No FBO files under {OUTCOME_DIR}", file=sys.stderr)
        return 1

    print(f"Extracting FBO debt outcomes for {len(targets)} year(s)\n")
    frames: list[pd.DataFrame] = []
    for year, source in targets:
        # Try the primary loader first (DOCX where available, otherwise PDF).
        # If the result is missing either debt line, try the PDF parser as a
        # fallback — older DOCX years (2019-20, 2020-21) don't include
        # Gross debt in the slim summary table but the PDF balance sheet does.
        dfs: list[pd.DataFrame] = []
        if source == "docx":
            try:
                dfs.append(fbo_debt.load_fbo_debt_docx(year))
            except Exception as exc:  # noqa: BLE001
                print(f"  {year} (docx): FAILED  ({type(exc).__name__}: {exc})",
                      file=sys.stderr)
        try:
            dfs.append(fbo_debt.load_fbo_debt_pdf(year))
        except Exception as exc:  # noqa: BLE001
            print(f"  {year} (pdf): FAILED  ({type(exc).__name__}: {exc})",
                  file=sys.stderr)
        if not dfs:
            continue
        df = pd.concat(dfs, ignore_index=True).drop_duplicates(
            subset=["fiscal_year", "line_item", "measure"], keep="first"
        )
        items = ", ".join(sorted(df["line_item"].unique())) if not df.empty else "(empty)"
        print(f"  {year}: {items}")
        frames.append(df)

    if not frames:
        print("\nNo data extracted.", file=sys.stderr)
        return 1

    combined = pd.concat(frames, ignore_index=True)
    PARQUET_DIR.mkdir(exist_ok=True)
    out = PARQUET_DIR / "fbo_debt.parquet"
    combined.to_parquet(out, index=False)
    print(f"\nWrote {len(combined)} rows to {out.relative_to(PARQUET_DIR.parent.parent)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
