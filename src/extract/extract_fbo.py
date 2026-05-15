"""Extract FBO Outcome data for every available year and write Parquet.

Scans `data/Outcome/` for fiscal-year directories and dispatches to the right parser:

- DOCX path (2019-20 onwards): `src.data.fbo_docx.load_fbo_outcome`
- PDF path (pre-2019-20):       `src.data.fbo_pdf.load_fbo_outcome`

For years that have both (2019-20 onwards), DOCX is preferred — Word tables are
more reliable to parse than PDF text positions. Results are concatenated and
written to `data/parquet/fbo_outcomes.parquet`.

Run:
    uv run python -m src.extract.extract_fbo
"""

from __future__ import annotations

import sys

import pandas as pd

from src.data import fbo_docx, fbo_pdf
from src.utilities.paths import OUTCOME_DIR, PARQUET_DIR


def _discover_years() -> list[tuple[str, str]]:
    """Return [(year, source), ...] sorted by year. Source is 'docx' or 'pdf'."""
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
        print(f"No FBO files found under {OUTCOME_DIR}", file=sys.stderr)
        return 1

    n_docx = sum(1 for _, s in targets if s == "docx")
    n_pdf = sum(1 for _, s in targets if s == "pdf")
    print(f"Extracting FBO Outcome for {len(targets)} year(s): "
          f"{n_docx} DOCX, {n_pdf} PDF\n")

    frames: list[pd.DataFrame] = []
    for year, source in targets:
        loader = fbo_docx.load_fbo_outcome if source == "docx" else fbo_pdf.load_fbo_outcome
        try:
            df = loader(year)
        except Exception as exc:  # noqa: BLE001 - top-level extract: surface every failure
            print(f"  {year} ({source}): FAILED  ({type(exc).__name__}: {exc})",
                  file=sys.stderr)
            continue
        print(f"  {year} ({source}): {len(df):3d} rows  "
              f"({df['line_item'].nunique()} unique line items)")
        frames.append(df)

    if not frames:
        print("\nNo data extracted.", file=sys.stderr)
        return 1

    combined = pd.concat(frames, ignore_index=True)
    PARQUET_DIR.mkdir(exist_ok=True)
    out = PARQUET_DIR / "fbo_outcomes.parquet"
    combined.to_parquet(out, index=False)

    print(f"\nWrote {len(combined)} rows to {out.relative_to(PARQUET_DIR.parent.parent)}")
    print(f"Years covered:     {', '.join(sorted(combined['fiscal_year'].unique()))}")
    print(f"Unique line items: {combined['line_item'].nunique()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
