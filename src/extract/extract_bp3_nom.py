"""Extract the BP3 Appendix-A NOM table from every available BP3 PDF
and write `data/parquet/bp3_nom.parquet`.

Run:
    uv run python -m src.extract.extract_bp3_nom
"""

from __future__ import annotations

import pandas as pd

from src.data.bp3_nom import load_bp3_nom
from src.utilities.paths import BUDGET_DIR, PARQUET_DIR


OUT_PATH = PARQUET_DIR / "bp3_nom.parquet"


def main() -> None:
    years = sorted(
        p.name for p in BUDGET_DIR.iterdir() if (p / "bp3.pdf").exists()
    )
    if not years:
        print("No BP3 PDFs found under data/Budget/")
        return

    frames: list[pd.DataFrame] = []
    for y in years:
        try:
            df = load_bp3_nom(y)
        except Exception as exc:  # noqa: BLE001
            print(f"  FAIL  {y}: {type(exc).__name__}: {exc}")
            continue
        if df.empty:
            print(f"  EMPTY {y}")
            continue
        print(f"  ok    {y}: {len(df)} rows")
        frames.append(df)

    if not frames:
        print("Nothing extracted; not writing parquet.")
        return

    out = pd.concat(frames, ignore_index=True)
    PARQUET_DIR.mkdir(parents=True, exist_ok=True)
    out.to_parquet(OUT_PATH, index=False)
    print(f"\nWrote {len(out)} rows to {OUT_PATH}")


if __name__ == "__main__":
    main()
