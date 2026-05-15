# Data policy

Decisions governing what is stored under `data/` and how it is organised.

## Directory layout

```
data/
├── Budget/   # Budget Paper No. 1 — forward estimates as delivered
├── MYEFO/    # Mid-Year Economic and Fiscal Outlook — mid-year revisions
└── Outcome/  # Final Budget Outcome — actuals
```

One subdirectory per fiscal year (`YYYY-YY`), starting at 2010-11.

## File naming

Inside each year folder, files use a stable stem regardless of the upstream filename:

- `bp1.pdf` — full Budget Paper No. 1 PDF (human-readable reference). Available for **all 17 budgets** (2010-11 → 2026-27).
- `bp1_bs-1.docx` … `bp1_bs-10.docx` — BP1 split per statement, as Word docs. **Only available for 2022-23, 2024-25, 2025-26, 2026-27.** Older budgets do not publish DOCX — the budget.gov.au server silently serves the *current* budget's DOCX as a fallback when an old-year DOCX URL is requested, so any "DOCX" for those years would be misleading.
- `fbo.pdf` — full Final Budget Outcome PDF (under `data/Outcome/`). Available for all completed fiscal years (2010-11 → 2024-25).
- `fbo_01_part_1.docx`, `fbo_02_part_2.docx`, `fbo_03_part_3.docx`, `fbo_05_appendix_a.docx`, `fbo_06_appendix_b.docx` — FBO split per part. The `04_*` position is intentionally empty in the upstream archive. **DOCX only from 2019-20 onwards.**
- Future additions: `myefo.pdf`, etc.

**Practical consequence:** BP1 data extraction uses PDF parsing (pdfplumber) for the 13 PDF-only years, and can optionally use DOCX for the 4 DOCX-available years. To keep the parser uniform across years, the default is to use PDF for all 17 budgets.

Upstream uses a different PDF filename almost every year (`bp1.pdf`, `bp1_consolidated.pdf`, `BP1_combined.pdf`, `Budget_Paper_No_1.pdf`, …); normalising at the storage layer lets downstream code locate any year's document by path alone.

**Why DOCX as well as PDF.** The DOCX files contain real Word tables (`<w:tbl>` XML elements) for the budget aggregates, revenue, and expenditure tables. Parsing them is dramatically simpler and more reliable than extracting tables from the PDFs, where layout heuristics would be needed. PDFs are kept as the human-readable reference; data extraction works from DOCX.

## FBO availability

Final Budget Outcomes are published ~3 months after fiscal year end. As of May 2026, `data/Outcome/` covers 2010-11 through 2024-25 (15 years). 2025-26 FBO is expected around September 2026.

## Year-specific decisions

**2022-23 → October 2022 paper only.** Two budgets were delivered for 2022-23: Frydenberg's March 2022 paper (pre-election, Coalition) and Chalmers' October 2022 paper (post-election, Labor). The March paper was not legislated; the October paper set the forward estimates that became the baseline. Comparing FBO against March would be apples-to-oranges.

**2020-21 → October 2020 delivery.** The May 2020 Budget was deferred to October 2020 due to COVID. It is still the 2020-21 Budget and is stored as such; skipping it would leave a gap in the series.
