"""Extract FBO function-level expenses outcomes for every available year.

DOCX path (2019-20 onwards): `src.data.fbo_function.load_fbo_function_docx`.
PDF path (pre-2019-20):       `src.data.fbo_function.load_fbo_function_pdf`.

Run:
    uv run python -m src.extract.extract_fbo_functions
"""

from __future__ import annotations

import sys

import pandas as pd

from src.data import fbo_function
from src.utilities.paths import OUTCOME_DIR, PARQUET_DIR


def _discover_years() -> list[tuple[str, str]]:
    if not OUTCOME_DIR.is_dir():
        return []
    out: list[tuple[str, str]] = []
    for d in sorted(OUTCOME_DIR.iterdir()):
        if not d.is_dir():
            continue
        if (d / "fbo_05_appendix_a.docx").exists():
            out.append((d.name, "docx"))
        elif (d / "fbo.pdf").exists():
            out.append((d.name, "pdf"))
    return out


def main() -> int:
    targets = _discover_years()
    if not targets:
        print(f"No FBO files found under {OUTCOME_DIR}", file=sys.stderr)
        return 1

    n_docx = sum(1 for _, s in targets if s == "docx")
    n_pdf = sum(1 for _, s in targets if s == "pdf")
    print(f"Extracting FBO function outcomes for {len(targets)} year(s): "
          f"{n_docx} DOCX, {n_pdf} PDF\n")

    frames: list[pd.DataFrame] = []
    for year, source in targets:
        loader = (fbo_function.load_fbo_function_docx if source == "docx"
                  else fbo_function.load_fbo_function_pdf)
        try:
            df = loader(year)
        except Exception as exc:  # noqa: BLE001
            print(f"  {year} ({source}): FAILED  ({type(exc).__name__}: {exc})",
                  file=sys.stderr)
            continue
        print(f"  {year} ({source}): {len(df):2d} rows  "
              f"({df['line_item'].nunique()} functions)")
        frames.append(df)

    if not frames:
        print("\nNo data extracted.", file=sys.stderr)
        return 1

    combined = pd.concat(frames, ignore_index=True)
    PARQUET_DIR.mkdir(exist_ok=True)
    out = PARQUET_DIR / "fbo_functions.parquet"
    combined.to_parquet(out, index=False)

    print(f"\nWrote {len(combined)} rows to {out.relative_to(PARQUET_DIR.parent.parent)}")
    print(f"Years covered:     {', '.join(sorted(combined['fiscal_year'].unique()))}")
    print(f"Unique functions:  {combined['line_item'].nunique()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
