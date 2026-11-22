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


def parse_dates(values: pd.Series, cfg: DatasetConfig, *, keep_time: bool = False
                ) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Returns (dates, rule_used, failure_reason); index aligned with `values` (blank -> NaT, no reason).
    keep_time=False (column type "date"): the time of day is dropped (and logged).
    keep_time=True  (column type "datetime"): the time is kept, converted to the business time zone."""
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
        kept = parsed[ok] if keep_time else parsed[ok].dt.normalize()
        out.loc[idx] = kept.astype("datetime64[us]")
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
    for suffix in (" %H:%M:%S", " %H:%M"):                      # 05/03/2025 14:30
        attempt(cfg.locale.date_format + suffix, "locale_datetime" if keep_time else "datetime_time_dropped")
    for fmt in p.extra_date_formats:
        attempt(fmt, f"date_format:{fmt}")
    for fmt in NAIVE_DATETIME_FORMATS:
        attempt(fmt, "iso_datetime" if keep_time else "datetime_time_dropped")

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
                    utc = pd.to_datetime(pick.astype("int64"), unit=unit, errors="coerce")
                    if p.timezone:                      # a Unix timestamp is UTC: show business time
                        utc = utc.dt.tz_localize("UTC").dt.tz_convert(p.timezone).dt.tz_localize(None)
                    accept(utc, name, in_range_only=True)
    if p.compact_dates and todo.any():
        compact = text[todo][text[todo].str.fullmatch(r"\d{8}").fillna(False)]
        if len(compact):
            accept(pd.to_datetime(compact, format="%Y%m%d", errors="coerce"), "compact_date", in_range_only=True)

    if todo.any() and cfg.locale.timezone_abbreviations and p.timezone:
        accept(_with_zone_abbreviation(text[todo], cfg), "timezone_abbreviation")
    if todo.any() and p.dateparser_fallback:
        accept(_dateparser(text[todo], cfg), "dateparser", in_range_only=True)

    reason = pd.Series(pd.NA, index=values.index, dtype="string")
    reason[todo] = _refusal_reasons(text[todo], p, cfg)
    reason[rule.eq("ambiguous_day_month")] = "ambiguous_day_month"
    rule[rule.eq("ambiguous_day_month")] = pd.NA
    return out, rule, reason


_ABBREV = r"^(?P<dt>.*\d{1,2}:\d{2}(?::\d{2})?)\s+(?P<zone>[A-Z]{2,5})$"


def _with_zone_abbreviation(left: pd.Series, cfg) -> pd.Series:
    """'2025-03-05 10:00 IST' -> 10:00 in the zone the LOCALE says IST means (India), then business time."""
    out = pd.Series(pd.NaT, index=left.index, dtype="datetime64[us]")
    m = left.str.extract(_ABBREV)
    for zone_abbr, zone in cfg.locale.timezone_abbreviations.items():
        pick = m["zone"].eq(zone_abbr).fillna(False)
        if not pick.any():
            continue
        local = pd.Series(pd.NaT, index=m.index[pick], dtype="datetime64[us]")
        for fmt in ["%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", cfg.locale.date_format + " %H:%M",
                    cfg.locale.date_format + " %H:%M:%S"]:
            todo = local.isna()
            if not todo.any():
                break
            local[todo] = pd.to_datetime(m.loc[local.index[todo], "dt"], format=fmt, errors="coerce")
        ok = local.notna()
        if ok.any():
            conv = (local[ok].dt.tz_localize(zone, ambiguous="NaT", nonexistent="NaT")
                    .dt.tz_convert(cfg.policies.timezone).dt.tz_localize(None))
            out[conv.index] = conv
    return out


def _dateparser(left: pd.Series, cfg) -> pd.Series:
    """Fallback for written dates, using dateparser (github.com/scrapinghub/dateparser, BSD-3-Clause).
    Strict: day, month AND year must all be present (partial dates are handled by our own rules), only the
    dataset's languages, no relative words ("yesterday"), no time-zone guessing, and digits-only values are
    left to the exact Unix/compact readers."""
    out = pd.Series(pd.NaT, index=left.index, dtype="datetime64[us]")
    # Only WRITTEN dates (with a word: "5th March 2025", "5 मार्च 2025"). Number-only dates are left to the
    # exact readers (so policies like two_digit_years keep control), and zoned ISO times to the time-zone rules.
    has_word = left.str.contains(r"[^\W\d_]", regex=True).fillna(False)   # any letter (Hindi vowel signs aren't \w)
    zoned = left.str.fullmatch(TZ_AWARE).fillna(False) | left.str.match(_ABBREV).fillna(False)
    iso_like = left.str.match(r"^\d{4}-\d{2}-\d{2}[T ]").fillna(False)
    candidates = left[has_word & ~zoned & ~iso_like]
    if candidates.empty:
        return out
    try:
        from dateparser.date import DateDataParser
    except ImportError:
        return out
    ddp = _dateparser_cache.get((tuple(cfg.locale.languages), cfg.locale.date_order))
    if ddp is None:
        ddp = DateDataParser(languages=cfg.locale.languages, settings={
            "DATE_ORDER": cfg.locale.date_order, "STRICT_PARSING": True, "RETURN_AS_TIMEZONE_AWARE": False,
            "PARSERS": ["custom-formats", "absolute-time"]})
        _dateparser_cache[(tuple(cfg.locale.languages), cfg.locale.date_order)] = ddp
    for i, v in candidates.items():
        try:
            d = ddp.get_date_data(v)
        except Exception:  # noqa: BLE001 - an odd string must never stop the run
            continue
        if d.date_obj is not None and d.period == "day":
            out[i] = pd.Timestamp(d.date_obj)
    return out


_dateparser_cache: dict = {}


def _refusal_reasons(left: pd.Series, p, cfg=None) -> pd.Series:
    r = pd.Series("unrecognised_date", index=left.index, dtype="string")
    assigned = pd.Series(False, index=left.index)
    checks = list(REFUSAL_PATTERNS)
    if not p.compact_dates:
        checks.append(("compact_date_not_enabled", r"^(19|20)\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])$"))
    if not p.unix_timestamps:
        checks.append(("unix_timestamp_not_enabled", r"^\d{10}$|^\d{13}$|^\d{16}$"))
    for name, rx in checks:
        hit = ~assigned & left.str.fullmatch(rx).fillna(False)
        r[hit] = name
        assigned |= hit
    # A number that IS a valid date code but lands outside the business range: say what it would have been,
    # e.g. "excel_serial_outside_date_range (=2025-03-30)" instead of a vague refusal.
    for i in left.index[~assigned & left.str.fullmatch(r"\d+(\.\d+)?").fillna(False)]:
        r[i] = _explain_number(left[i], p, cfg)
    return r


def _explain_number(text: str, p, cfg) -> str:
    rng = f" outside {cfg.date_range.min}..{cfg.date_range.max}" if cfg is not None else ""
    digits = text.split(".")[0]
    if p.compact_dates and len(text) == 8 and text.isdigit():
        d = pd.to_datetime(text, format="%Y%m%d", errors="coerce")
        if pd.notna(d):
            return f"compact_date_outside_date_range (={d.date()}{rng})"
    if p.unix_timestamps and text.isdigit() and len(text) in UNIX_UNITS:
        unit = UNIX_UNITS[len(text)][0]
        d = pd.to_datetime(int(text), unit=unit, errors="coerce")
        if pd.notna(d):
            return f"unix_timestamp_outside_date_range (={d:%Y-%m-%d %H:%M} UTC{rng})"
    try:
        n = float(text)
    except ValueError:
        n = None
    if p.excel_serial_dates and n is not None and 1 <= n <= 200000 and len(digits) <= 6:
        d = EXCEL_EPOCH + pd.to_timedelta(n, unit="D")
        when = f"{d:%Y-%m-%d %H:%M}" if d != d.normalize() else f"{d.date()}"
        return f"excel_serial_outside_date_range (={when}{rng})"
    return "number_is_not_a_date"


def _flag_ambiguous(text, todo, rule):
    parts = text.str.extract(r"^(\d{1,2})[/.\-](\d{1,2})[/.\-]\d{2,4}$").astype("Int64")
    amb = todo & (parts[0] <= 12).fillna(False) & (parts[1] <= 12).fillna(False) & (parts[0] != parts[1]).fillna(False)
    rule[amb] = "ambiguous_day_month"
