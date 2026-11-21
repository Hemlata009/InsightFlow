"""Turn date TEXT into dates (vectorized). The locale decides day/month order; nothing is guessed.

Order of attempts for each value:
  1. the locale's own format (e.g. %d/%m/%Y for en_IN)          -> rule "locale_format" (not logged)
  2. each extra format from the policies (ISO, 05-Mar-26, ...)   -> rule "date_format:<fmt>"
  3. Excel serial numbers (45746)                               -> rule "excel_serial"
Anything left is NOT converted and reported with a reason.
"""

from __future__ import annotations

import pandas as pd

from insightflow.config import DatasetConfig

EXCEL_EPOCH = pd.Timestamp("1899-12-30")


def parse_dates(values: pd.Series, cfg: DatasetConfig) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Returns (dates, rule_used, failure_reason); index aligned with `values` (blank -> NaT, no reason)."""
    text = values.astype("string").str.strip()
    out = pd.Series(pd.NaT, index=values.index, dtype="datetime64[us]")
    rule = pd.Series(pd.NA, index=values.index, dtype="string")
    todo = text.notna() & text.ne("")

    def attempt(fmt: str, name: str):
        nonlocal todo
        if not todo.any():
            return
        parsed = pd.to_datetime(text[todo], format=fmt, errors="coerce")
        ok = parsed.notna()
        idx = parsed[ok].index
        out.loc[idx] = parsed[ok].astype("datetime64[us]")
        rule.loc[idx] = name
        todo = todo & ~text.index.isin(idx)

    p = cfg.policies
    if p.ambiguous_dates == "quarantine":
        _flag_ambiguous(text, todo, rule)
        todo = todo & rule.isna()
    attempt(cfg.locale.date_format, "locale_format")
    for fmt in p.extra_date_formats:
        attempt(fmt, f"date_format:{fmt}")
    # ISO with a time part, e.g. "2026-03-05 10:30:00" (Excel exports): keep the date
    attempt("%Y-%m-%d %H:%M:%S", "datetime_time_dropped")

    if p.excel_serial_dates and todo.any():
        num = pd.to_numeric(text[todo], errors="coerce")
        whole = num.notna() & (num == num.round()) & num.between(1, 200000)
        cand = pd.to_datetime(EXCEL_EPOCH) + pd.to_timedelta(num[whole], unit="D")
        lo, hi = pd.Timestamp(cfg.date_range.min), pd.Timestamp(cfg.date_range.max)
        inside = cand[(cand >= lo) & (cand <= hi)]   # only accept serials that land in the business range
        out.loc[inside.index] = inside.astype("datetime64[us]")
        rule.loc[inside.index] = "excel_serial"
        todo = todo & ~text.index.isin(inside.index)

    reason = pd.Series(pd.NA, index=values.index, dtype="string")
    reason[todo] = "unrecognised_date"
    reason[rule.eq("ambiguous_day_month")] = "ambiguous_day_month"
    rule[rule.eq("ambiguous_day_month")] = pd.NA
    return out, rule, reason


def _flag_ambiguous(text, todo, rule):
    parts = text.str.extract(r"^(\d{1,2})[/.\-](\d{1,2})[/.\-]\d{2,4}$").astype("Int64")
    amb = todo & (parts[0] <= 12).fillna(False) & (parts[1] <= 12).fillna(False) & (parts[0] != parts[1]).fillna(False)
    rule[amb] = "ambiguous_day_month"
