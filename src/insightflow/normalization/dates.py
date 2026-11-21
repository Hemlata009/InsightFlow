"""Turn date TEXT into dates (vectorized). The locale decides day/month order; nothing is guessed.

Attempts, in order (each value takes the first that works):
  1. the locale's own format, e.g. %d/%m/%Y                     -> "locale_format" (not logged)
  2. the locale format with a 2-digit year (05/03/26)            -> "two_digit_year"
  3. extra formats from the policies (ISO, 05-Mar-26, ...)       -> "date_format:<fmt>"
  4. date + time without a zone (time dropped)                   -> "datetime_time_dropped"
  5. date + time WITH a zone (+05:30 / Z), converted to the
     business time zone first (handles daylight saving)          -> "timezone_converted"
  6. Excel serial numbers, also with a time fraction (45746.5)   -> "excel_serial"
  7. Unix timestamps in s / ms / µs (only if enabled)            -> "unix_seconds" / "unix_ms" / "unix_us"
  8. compact 20250305 (only if enabled)                          -> "compact_date"
Numeric candidates (6–8) are accepted only if they land inside the dataset date range.
Anything left is NOT converted; it gets a specific reason.
"""

from __future__ import annotations

import pandas as pd

from insightflow.config import DatasetConfig

EXCEL_EPOCH = pd.Timestamp("1899-12-30")
NAIVE_DATETIME_FORMATS = ["%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M",
                          "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%d %H:%M:%S.%f"]
TZ_AWARE = r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?\s*(Z|[+-]\d{2}:?\d{2})$"
UNIX_UNITS = {10: ("s", "unix_seconds"), 13: ("ms", "unix_ms"), 16: ("us", "unix_us")}

# Why a leftover value was refused (checked in this order)
REFUSAL_PATTERNS = [
    ("missing_year", r"^\d{1,2}[/.\-]\d{1,2}$|^\d{1,2}[\s\-]?[A-Za-z]{3,9}\.?$|^[A-Za-z]{3,9}\.?\s+\d{1,2}$"),
    ("missing_day", r"^[A-Za-z]{3,9}\.?[\s\-,]+\d{2,4}$|^\d{1,2}[/.\-]\d{4}$|^\d{4}[/.\-]\d{1,2}$"),
    ("timezone_not_configured", TZ_AWARE),
    ("timezone_name_ambiguous", r"^.*\d{1,2}:\d{2}(:\d{2})?\s+[A-Z]{2,5}$"),     # "10:00 IST": IST = India or Israel?
]


def parse_dates(values: pd.Series, cfg: DatasetConfig) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Returns (dates, rule_used, failure_reason); index aligned with `values` (blank -> NaT, no reason)."""
    text = values.astype("string").str.strip()
    out = pd.Series(pd.NaT, index=values.index, dtype="datetime64[us]")
    rule = pd.Series(pd.NA, index=values.index, dtype="string")
    todo = text.notna() & text.ne("")
    p = cfg.policies
    lo, hi = pd.Timestamp(cfg.date_range.min), pd.Timestamp(cfg.date_range.max) + pd.Timedelta(days=1)

    def accept(parsed: pd.Series, name: str, in_range_only: bool = False):
        nonlocal todo
        ok = parsed.notna()
        if in_range_only:
            ok &= (parsed >= lo) & (parsed < hi)
        idx = parsed[ok].index
        out.loc[idx] = parsed[ok].dt.normalize().astype("datetime64[us]")
        rule.loc[idx] = name
        todo = todo & ~text.index.isin(idx)

    def attempt(fmt: str, name: str):
        if todo.any():
            accept(pd.to_datetime(text[todo], format=fmt, errors="coerce"), name)

    if p.ambiguous_dates == "quarantine":
        _flag_ambiguous(text, todo, rule)
        todo = todo & rule.isna()
    attempt(cfg.locale.date_format, "locale_format")
    if p.two_digit_years and "%Y" in cfg.locale.date_format:
        short = text[todo].str.fullmatch(r"\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2}").fillna(False)
        if short.any():
            accept(pd.to_datetime(text[todo][short], format=cfg.locale.date_format.replace("%Y", "%y"),
                                  errors="coerce"), "two_digit_year")
    for fmt in p.extra_date_formats:
        attempt(fmt, f"date_format:{fmt}")
    for fmt in NAIVE_DATETIME_FORMATS:
        attempt(fmt, "datetime_time_dropped")

    if todo.any() and p.timezone:
        aware = text[todo].str.fullmatch(TZ_AWARE).fillna(False)
        if aware.any():
            vals = text[todo][aware].str.replace(r"\s+(?=Z|[+-]\d)", "", regex=True)
            parsed = pd.to_datetime(vals, utc=True, errors="coerce", format="ISO8601")
            local = parsed.dt.tz_convert(p.timezone).dt.tz_localize(None)
            accept(local, "timezone_converted")

    if todo.any():
        num = pd.to_numeric(text[todo], errors="coerce")
        if p.excel_serial_dates:
            serial = num[num.notna() & num.between(1, 200000)]
            accept(EXCEL_EPOCH + pd.to_timedelta(serial, unit="D"), "excel_serial", in_range_only=True)
        if p.unix_timestamps and todo.any():
            digits = text[todo].str.len()
            whole = text[todo].str.fullmatch(r"\d+").fillna(False)
            for n, (unit, name) in UNIX_UNITS.items():
                pick = text[todo][whole & digits.eq(n)]
                if len(pick):
                    accept(pd.to_datetime(pick.astype("int64"), unit=unit, errors="coerce"), name, in_range_only=True)
    if p.compact_dates and todo.any():
        compact = text[todo][text[todo].str.fullmatch(r"\d{8}").fillna(False)]
        if len(compact):
            accept(pd.to_datetime(compact, format="%Y%m%d", errors="coerce"), "compact_date", in_range_only=True)

    reason = pd.Series(pd.NA, index=values.index, dtype="string")
    reason[todo] = _refusal_reasons(text[todo], p)
    reason[rule.eq("ambiguous_day_month")] = "ambiguous_day_month"
    rule[rule.eq("ambiguous_day_month")] = pd.NA
    return out, rule, reason


def _refusal_reasons(left: pd.Series, p) -> pd.Series:
    r = pd.Series("unrecognised_date", index=left.index, dtype="string")
    assigned = pd.Series(False, index=left.index)
    checks = list(REFUSAL_PATTERNS)
    if not p.compact_dates:
        checks.append(("compact_date_not_enabled", r"^(19|20)\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])$"))
    if not p.unix_timestamps:
        checks.append(("unix_timestamp_not_enabled", r"^\d{10}$|^\d{13}$|^\d{16}$"))
    checks.append(("outside_date_range_or_not_a_date", r"^\d+(\.\d+)?$"))   # numbers that were no valid serial
    for name, rx in checks:
        hit = ~assigned & left.str.fullmatch(rx).fillna(False)
        r[hit] = name
        assigned |= hit
    return r


def _flag_ambiguous(text, todo, rule):
    parts = text.str.extract(r"^(\d{1,2})[/.\-](\d{1,2})[/.\-]\d{2,4}$").astype("Int64")
    amb = todo & (parts[0] <= 12).fillna(False) & (parts[1] <= 12).fillna(False) & (parts[0] != parts[1]).fillna(False)
    rule[amb] = "ambiguous_day_month"
