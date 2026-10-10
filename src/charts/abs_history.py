"""Chart-time ABS data fetching for the 6 BP1 Table 1.1 major economic parameters.

No persistent parquet — each chart run fetches fresh ABS data via `readabs`.
Series IDs are resolved at fetch time via description-based lookup
(`ra.find_abs_id`) so the parser doesn't break when ABS reissues a table with
new IDs.

Each series is returned at its **native frequency** (no resampling). The
chart layer inspects `series.index.freq` and anchors the BP1 annual forecast
points to the matching period (Jun quarter for quarterly series, Jun month
for monthly).

Transforms per series per Table 2.2 footnote:

- Real / Nominal GDP (quarterly NA) — 4-quarter rolling-sum YoY growth. At
  Jun-quarter this equals Treasury's "% change on preceding year".
- CPI / WPI (quarterly index) — through-year growth: `pct_change(4)`.
- Employment (monthly LFS) — through-year growth: `pct_change(12)`. At Jun
  month this matches Treasury's "through-the-year growth to June quarter"
  to within sub-monthly noise.
- Unemployment rate (monthly SA rate) — level, no transform. Treasury's
  "rate for the June quarter" sits at the Jun observation.
"""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd
import readabs as ra
from readabs import metacol as mc

# Catalogue / table constants
_GDP_CAT = "5206.0"
_GDP_KAGS = "5206001_Key_Aggregates"
_GDP_EXP = "5206002_Expenditure_Volume_Measures"
_GDP_IPD = "5206005_Expenditure_Implicit_Price_Deflators"
_GDP_HHC = "5206008_Household_Final_Consumption_Expenditure"
_GDP_SAS = "5206024_Selected_Analytical_Series"
_CPI_CAT = "6401.0"
_CPI_APP = "64010Appendix1a"
_WPI_CAT = "6345.0"
_WPI_TABLE = "634501"
_LFS_CAT = "6202.0"
_LFS_TABLE = "6202001"
_NOM_CAT = "3101.0"
_NOM_TABLE = "310102"
_BOP_CAT = "5302.0"
_BOP_TABLE = "530204"


# Description filters per line item. No hardcoded series IDs — every series
# is resolved at fetch time via ra.find_abs_id(). Filter dicts use the
# readabs convention `{value_to_match: metacol_name}` (same orientation as
# the SOMP notebook).
_DESCRIPTIONS: dict[str, tuple[str, str, dict]] = {
    "Real gross domestic product": (
        _GDP_CAT,
        _GDP_KAGS,
        {
            "Gross domestic product: Chain volume measures ;": mc.did,
            "Seasonally Adjusted": mc.stype,
            "$ Millions": mc.unit,
        },
    ),
    "Nominal gross domestic product": (
        _GDP_CAT,
        _GDP_KAGS,
        {
            "Gross domestic product: Current prices ;": mc.did,
            "Seasonally Adjusted": mc.stype,
            "$ Millions": mc.unit,
        },
    ),
    "Consumer price index": (
        _CPI_CAT,
        _CPI_APP,
        {
            "All groups CPI, seasonally adjusted": mc.did,
            "Index Numbers": mc.unit,
        },
    ),
    "Wage price index": (
        _WPI_CAT,
        _WPI_TABLE,
        # Total hourly rates of pay excluding bonuses, all industries, both
        # sectors, SA. ABS's DID uses double spaces after each semicolon.
        {
            (
                "Quarterly Index ;  Total hourly rates of pay excluding bonuses ;  "
                "Australia ;  Private and Public ;  All industries ;"
            ): mc.did,
            "Seasonally Adjusted": mc.stype,
        },
    ),
    "Employment": (
        _LFS_CAT,
        _LFS_TABLE,
        {
            "Employed total ;  Persons ;": mc.did,
            "Seasonally Adjusted": mc.stype,
            "000": mc.unit,
        },
    ),
    "Unemployment rate (per cent)": (
        _LFS_CAT,
        _LFS_TABLE,
        {
            "Unemployment rate ;  Persons ;": mc.did,
            "Seasonally Adjusted": mc.stype,
            "Percent": mc.unit,
        },
    ),
    "Net overseas migration": (
        _NOM_CAT,
        _NOM_TABLE,
        # ABS publishes NOM as Original only; no SA series exists.
        {
            "Net Overseas Migration ;  Australia ;": mc.did,
            "Original": mc.stype,
            "Number": mc.unit,
        },
    ),
    # ----- BP1 Statement 2 demand-side aggregates (CVM, "% change on
    # preceding year"). All resolve from 5206.0 quarterly NA. Each uses
    # _rolling_4q_growth so the Jun-quarter value equals Treasury's FY
    # convention.
    "Household consumption": (
        _GDP_CAT,
        _GDP_HHC,
        # In the HHC-specific table, "FINAL CONSUMPTION EXPENDITURE" is by
        # definition households-only.
        {
            "FINAL CONSUMPTION EXPENDITURE: Chain volume measures ;": mc.did,
            "Seasonally Adjusted": mc.stype,
            "$ Millions": mc.unit,
        },
    ),
    "Dwelling investment": (
        _GDP_CAT,
        _GDP_EXP,
        # Private dwelling investment (the GFCF component reported in BP1).
        {
            "Dwellings - Total": mc.did,
            "Private": mc.did,
            "Seasonally Adjusted": mc.stype,
            "$ Millions": mc.unit,
        },
    ),
    "Total business investment": (
        _GDP_CAT,
        _GDP_EXP,
        # BP1's "Total business investment" maps to ABS's "Total private
        # business investment" (broader than SOMP's "New private business
        # investment" — includes net 2nd-hand purchases and cultivated
        # biological resources).
        {
            "Private ;  Gross fixed capital formation - Total private business investment ;": mc.did,
            "Seasonally Adjusted": mc.stype,
            "$ Millions": mc.unit,
        },
    ),
    "Public final demand": (
        _GDP_CAT,
        _GDP_SAS,
        {
            "Public ;  Final demand: Chain volume measures ;": mc.did,
            "Seasonally Adjusted": mc.stype,
            "$ Millions": mc.unit,
        },
    ),
    "Gross national expenditure": (
        _GDP_CAT,
        _GDP_EXP,
        {
            "Gross national expenditure ;": mc.did,
            "Seasonally Adjusted": mc.stype,
            "$ Millions": mc.unit,
        },
    ),
    "Exports of goods and services": (
        _GDP_CAT,
        _GDP_EXP,
        {
            "Exports of goods and services": mc.did,
            "Seasonally Adjusted": mc.stype,
            "$ Millions": mc.unit,
        },
    ),
    "Imports of goods and services": (
        _GDP_CAT,
        _GDP_EXP,
        {
            "Imports of goods and services": mc.did,
            "Seasonally Adjusted": mc.stype,
            "$ Millions": mc.unit,
        },
    ),
    "Terms of trade": (
        _GDP_CAT,
        _GDP_KAGS,
        # Terms of trade index, SA. BP1 reports "% change on preceding year"
        # which equals FY-mean / prior FY-mean - 1 — same as rolling-4q on
        # an index (mean and sum scale identically).
        {
            "Terms of trade: Index ;": mc.did,
            "Seasonally Adjusted": mc.stype,
            "Index Numbers": mc.unit,
        },
    ),
    "GDP deflator": (
        _GDP_CAT,
        _GDP_IPD,
        {
            "GROSS DOMESTIC PRODUCT ;": mc.did,
            "Seasonally Adjusted": mc.stype,
            "Index Numbers": mc.unit,
        },
    ),
    "Private final demand": (
        _GDP_CAT,
        _GDP_SAS,
        {
            "Private ;  Final demand: Chain volume measures ;": mc.did,
            "Seasonally Adjusted": mc.stype,
            "$ Millions": mc.unit,
        },
    ),
    "Mining investment": (
        _GDP_CAT,
        _GDP_SAS,
        {
            "Gross fixed capital formation - Mining private business investment: Chain volume measures ;": mc.did,
            "Seasonally Adjusted": mc.stype,
            "$ Millions": mc.unit,
        },
    ),
    "Non-mining investment": (
        _GDP_CAT,
        _GDP_SAS,
        {
            "Gross fixed capital formation - Non-mining private business investment: Chain volume measures ;": mc.did,
            "Seasonally Adjusted": mc.stype,
            "$ Millions": mc.unit,
        },
    ),
    "Participation rate (per cent)": (
        _LFS_CAT,
        _LFS_TABLE,
        {
            "Participation rate ;  Persons ;": mc.did,
            "Seasonally Adjusted": mc.stype,
            "Percent": mc.unit,
        },
    ),
    # Internal-use: CVM levels needed for the Change in inventories
    # contribution-to-growth calculation. Not exposed via SUPPORTED_LINE_ITEMS
    # (see _COMPUTED_LINE_ITEMS below).
    "_Changes in inventories CVM": (
        _GDP_CAT,
        _GDP_EXP,
        {
            "Changes in inventories ;": mc.did,
            "Seasonally Adjusted": mc.stype,
            "$ Millions": mc.unit,
        },
    ),
    # Internal-use: Current account balance ($M SA quarterly), used as the
    # numerator of the CAB / Nominal GDP ratio.
    "_Current account balance": (
        _BOP_CAT,
        _BOP_TABLE,
        {
            "Current account ;": mc.did,
            "Seasonally Adjusted": mc.stype,
            "$ Millions": mc.unit,
        },
    ),
}


# Line items whose history is computed rather than fetched directly. These
# appear in SUPPORTED_LINE_ITEMS for chart wiring, but fetch_history routes
# them through their own bespoke calculation.
_COMPUTED_LINE_ITEMS = (
    "Change in inventories",
    "Current account balance (per cent of GDP)",
)


SUPPORTED_LINE_ITEMS = [k for k in _DESCRIPTIONS if not k.startswith("_")] + list(_COMPUTED_LINE_ITEMS)


def _fetch_raw(line_item: str) -> pd.Series:
    if line_item not in _DESCRIPTIONS:
        raise ValueError(f"Unsupported line item: {line_item!r}")
    cat, table, filters = _DESCRIPTIONS[line_item]
    data, meta = ra.read_abs_cat(cat, single_excel_only=table)
    _, series_id, _ = ra.find_abs_id(meta, filters)
    return data[table][series_id]


def _rolling_4q_growth(series: pd.Series) -> pd.Series:
    """4-quarter rolling sum YoY growth.

    Treasury's "percentage change on preceding year" (Real GDP, Nominal GDP)
    is the annual sum vs preceding annual sum. At quarterly cadence:

        sum_4q(t) / sum_4q(t).shift(4) - 1

    At Jun-quarter, sum_4q is the FY total, so this equals Treasury's published
    FY-on-FY rate.
    """
    rolling = series.rolling(4).sum()
    return ((rolling / rolling.shift(4)) - 1.0) * 100.0


def _rolling_4q_sum(series: pd.Series) -> pd.Series:
    """4-quarter rolling sum.

    At Jun-quarter this equals the FY total — matches Treasury's annual NOM convention.
    """
    return series.rolling(4).sum()


def _annual_contribution_to_gdp(component_levels: pd.Series, gdp_levels: pd.Series) -> pd.Series:
    """Annual % pt contribution of a CVM component to FY-on-FY GDP growth.

    At Jun-q this equals (X_FY_t - X_FY_{t-1}) / GDP_FY_{t-1} * 100 — BP1's
    "percentage point contribution" convention. The rolling-4q-sum form
    extends the same metric to quarterly cadence so the chart line is
    continuous between Jun-quarters.
    """
    comp_4q = component_levels.rolling(4).sum()
    gdp_4q = gdp_levels.rolling(4).sum()
    return (comp_4q - comp_4q.shift(4)) / gdp_4q.shift(4) * 100.0


def _annual_ratio_to_gdp(numerator_levels: pd.Series, gdp_levels: pd.Series) -> pd.Series:
    """Annual ratio (FY total / FY total) × 100, e.g. CAB as % of GDP.

    Both inputs must be in the same price basis (typically nominal $).
    At Jun-q this equals FY-sum(numerator) / FY-sum(GDP) × 100 — Treasury's
    "% of GDP" convention.
    """
    num_4q = numerator_levels.rolling(4).sum()
    gdp_4q = gdp_levels.rolling(4).sum()
    return (num_4q / gdp_4q) * 100.0


def _through_year_growth(series: pd.Series) -> pd.Series:
    """Through-the-year growth at native cadence.

    Uses the period frequency to pick the correct lag: monthly → 12, quarterly
    → 4. At Jun (month or quarter) the value equals Treasury's annual
    "through-the-year growth to June quarter".
    """
    index = series.index
    freq = index.freqstr if isinstance(index, pd.PeriodIndex) else ""
    if freq.startswith("M"):
        lag = 12
    elif freq.startswith("Q"):
        lag = 4
    else:
        raise ValueError(f"Unsupported series frequency for through-year growth: {freq!r}")
    return series.pct_change(lag) * 100.0


def _level(series: pd.Series) -> pd.Series:
    """Return the series unchanged: a monthly SA rate, plotted directly as a level."""
    return series


# Line items that are one ABS series with one transform. BP1 demand-side
# aggregates and indexes follow the same FY-on-FY convention as GDP: for flow
# series the rolling sum equals the FY total; for indexes rolling-sum/shift
# equals rolling-mean/shift, so the same transform produces Treasury's
# "% change on preceding year".
_TRANSFORMS: dict[str, Callable[[pd.Series], pd.Series]] = {
    **dict.fromkeys(
        (
            "Real gross domestic product",
            "Nominal gross domestic product",
            "Household consumption",
            "Dwelling investment",
            "Total business investment",
            "Public final demand",
            "Private final demand",
            "Mining investment",
            "Non-mining investment",
            "Gross national expenditure",
            "Exports of goods and services",
            "Imports of goods and services",
            "Terms of trade",
            "GDP deflator",
        ),
        _rolling_4q_growth,
    ),
    **dict.fromkeys(("Consumer price index", "Wage price index", "Employment"), _through_year_growth),
    **dict.fromkeys(("Unemployment rate (per cent)", "Participation rate (per cent)"), _level),
    "Net overseas migration": _rolling_4q_sum,
}


def fetch_history(line_item: str) -> pd.Series:
    """Fetch and transform ABS history for one BP1 Table 1.1 line item.

    Returns the transformed series at its native ABS frequency. At Jun-quarter
    (quarterly series) or Jun-month (monthly series), the value matches
    Treasury's annual published figure to within rounding.
    """
    # Computed line items — bespoke pipelines that don't fit the
    # "fetch one series + apply one transform" shape.
    if line_item == "Change in inventories":
        cii = _fetch_raw("_Changes in inventories CVM")
        gdp = _fetch_raw("Real gross domestic product")
        return _annual_contribution_to_gdp(cii, gdp)
    if line_item == "Current account balance (per cent of GDP)":
        cab = _fetch_raw("_Current account balance")
        # Denominator is nominal GDP — CAB is in $ (current prices).
        nominal_gdp = _fetch_raw("Nominal gross domestic product")
        return _annual_ratio_to_gdp(cab, nominal_gdp)

    transform = _TRANSFORMS.get(line_item)
    if transform is None:
        raise ValueError(f"Unhandled line item: {line_item!r}")
    return transform(_fetch_raw(line_item))
