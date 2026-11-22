"""Edge-case group 3: dates, times, time zones."""

import pandas as pd
import pytest
from pydantic import ValidationError

from insightflow.config import load_dataset_config
from insightflow.ingestion import SOURCE_ROW
from insightflow.normalization import normalize, parse_dates

IN = load_dataset_config("SALES_002")          # en_IN, DMY, Asia/Kolkata, 2025-01-01 .. 2026-06-30
US = load_dataset_config("SALES_001")          # en_US, MDY, no time zone, 2014 .. 2017


def cfg_with(base=IN, **policy):
    c = base.model_copy(deep=True)
    for k, v in policy.items():
        setattr(c.policies, k, v)
    return c


def run(values, cfg=IN):
    d, rule, reason = parse_dates(pd.Series(values, dtype="string"), cfg)
    return ([x.date().isoformat() if pd.notna(x) else None for x in d],
            [None if pd.isna(x) else x for x in rule], [None if pd.isna(x) else x for x in reason])


# ---------------- years and days
def test_two_digit_years():
    d, rule, _ = run(["05/03/26", "05/03/2026"])
    assert d == ["2026-03-05", "2026-03-05"] and rule == ["two_digit_year", "locale_format"]
    off = run(["05/03/26"], cfg_with(two_digit_years=False))
    assert off[0] == [None]


@pytest.mark.parametrize("value, reason", [("05/03", "missing_year"), ("5 Mar", "missing_year"), ("Mar 5", "missing_year"),
                                           ("Feb 2025", "missing_day"), ("03/2025", "missing_day"), ("2025-03", "missing_day")])
def test_incomplete_dates_are_refused_with_a_clear_reason(value, reason):
    d, _, r = run([value])
    assert d == [None] and r == [reason]


def test_leap_days():
    d, _, r = run(["29/02/2024", "29/02/2025"], cfg_with(IN))
    assert d[0] == "2024-02-29" and d[1] is None and r[1] == "unrecognised_date"


# ---------------- Excel, Unix, compact
def test_excel_serial_with_time_fraction():
    d, rule, _ = run(["45746", "45746.75"])
    assert d == ["2025-03-30", "2025-03-30"] and rule == ["excel_serial", "excel_serial"]


@pytest.mark.parametrize("value", ["1741132800", "1741132800000", "1741132800000000"])   # 2025-03-05 00:00 UTC
def test_unix_timestamps_when_enabled(value):
    d, rule, _ = run([value], cfg_with(unix_timestamps=True))
    assert d == ["2025-03-05"] and rule[0].startswith("unix_")


def test_unix_timestamps_on_by_default_and_can_be_switched_off():
    assert run(["1741132800"])[0] == ["2025-03-05"]                  # inside the date range: accepted
    d, _, r = run(["1741132800"], cfg_with(unix_timestamps=False))
    assert d == [None] and r == ["unix_timestamp_not_enabled"]


def test_unix_timestamp_outside_range_refused():
    d, _, _ = run(["946684800"], cfg_with(unix_timestamps=True))   # 2000-01-01: 9 digits and out of range
    assert d == [None]


def test_compact_dates_on_by_default_and_can_be_switched_off():
    assert run(["20250305"], cfg_with(compact_dates=False))[2] == ["compact_date_not_enabled"]
    d, rule, _ = run(["20250305", "20990101"], cfg_with(compact_dates=True))
    assert d == ["2025-03-05", None] and rule[0] == "compact_date"       # 2099 is outside the date range


# ---------------- times and time zones
def test_naive_datetimes_keep_their_date():
    d, rule, _ = run(["2025-03-05T23:59:59", "2025-03-05 10:15", "2025-03-05T10:15:00.123"])
    assert d == ["2025-03-05"] * 3 and set(rule) == {"datetime_time_dropped"}


def test_timezone_conversion_changes_the_business_date():
    # 20:00 UTC on 5 March is already 01:30 on 6 March in India.
    d, rule, _ = run(["2025-03-05T20:00:00Z", "2025-03-05T20:00:00+05:30", "2025-03-05 20:00:00 +0000"])
    assert d == ["2025-03-06", "2025-03-05", "2025-03-06"] and set(rule) == {"timezone_converted"}


def test_daylight_saving_transitions_new_york():
    ny = cfg_with(US, timezone="America/New_York")
    ny.date_range.min, ny.date_range.max = pd.Timestamp("2025-01-01").date(), pd.Timestamp("2025-12-31").date()
    d, _, _ = run([
        "2025-03-09T06:30:00Z",   # 01:30 EST, just before the spring-forward jump -> 9 March
        "2025-03-10T03:30:00Z",   # 23:30 EDT (UTC-4 after the jump) -> still 9 March
        "2025-11-02T04:30:00Z",   # 00:30 EDT on fall-back day -> 2 November
        "2025-11-03T04:30:00Z",   # 23:30 EST (UTC-5 after fall-back) -> 2 November
    ], ny)
    assert d == ["2025-03-09", "2025-03-09", "2025-11-02", "2025-11-02"]


def test_zoned_times_need_a_configured_timezone():
    d, _, r = run(["2015-03-05T20:00:00Z"], US)                   # SALES_001 has no business time zone
    assert d == [None] and r == ["timezone_not_configured"]


def test_zone_abbreviations_are_ambiguous_without_a_locale_mapping():
    d, _, r = run(["2015-03-05 10:00 IST"], US)                  # US data: India or Israel Standard Time?
    assert d == [None] and r == ["timezone_name_ambiguous"]


def test_ist_means_india_in_an_indian_dataset():
    d, rule, _ = run(["2025-03-05 23:30 IST"])                   # SALES_002 locale maps IST -> Asia/Kolkata
    assert d == ["2025-03-05"] and rule == ["timezone_abbreviation"]


@pytest.mark.parametrize("value", ["5th March 2025", "March 5, 2025", "5 मार्च 2025"])
def test_written_dates_via_dateparser(value):
    d, rule, _ = run([value])
    assert d == ["2025-03-05"] and rule == ["dateparser"]


def test_dateparser_never_guesses_missing_parts_or_relative_words():
    _, _, r = run(["yesterday", "next friday", "Mar 2025", "05/03"], cfg_with(
        partial_dates=IN.policies.partial_dates.model_copy(update={"missing_day": "quarantine"})))
    assert r == ["unrecognised_date", "unrecognised_date", "missing_day", "missing_year"]


def test_unknown_timezone_rejected_in_config():
    with pytest.raises(ValidationError, match="unknown timezone"):
        type(IN.policies).model_validate({**IN.policies.model_dump(), "timezone": "Mars/Olympus"})


# ---------------- dates inside ID columns are left alone
def test_date_like_ids_stay_text():
    df = pd.DataFrame({"Order_ID": ["2025-03-05", "20250305"], "Order_Date": ["05/03/2025", "06/03/2025"]},
                      dtype="string")
    df.insert(0, SOURCE_ROW, [2, 3])
    n = normalize(df, IN)
    assert list(n.data["Order_ID"]) == ["2025-03-05", "20250305"]
    assert str(n.data["Order_ID"].dtype) == "string"


def test_date_numbers_outside_the_range_say_what_they_would_be():
    """User test on SALES_001 (2014-2017): 2025 date numbers are refused, but the reason shows the reading."""
    d, _, r = run(["45746", "45746.75", "99999", "1741132800", "20250305", "123456789012"], US)
    assert d == [None] * 6
    assert r[0] == "excel_serial_outside_date_range (=2025-03-30 outside 2014-01-01..2017-12-31)"
    assert r[1] == "excel_serial_outside_date_range (=2025-03-30 18:00 outside 2014-01-01..2017-12-31)"
    assert r[2] == "excel_serial_outside_date_range (=2173-10-13 outside 2014-01-01..2017-12-31)"
    assert r[3] == "unix_timestamp_outside_date_range (=2025-03-05 00:00 UTC outside 2014-01-01..2017-12-31)"
    assert r[4] == "compact_date_outside_date_range (=2025-03-05 outside 2014-01-01..2017-12-31)"
    assert r[5] == "number_is_not_a_date"


def test_same_date_numbers_accepted_where_the_range_fits():
    d, rule, _ = run(["45746", "1741132800", "20250305"])                  # SALES_002: 2025-2026
    assert d == ["2025-03-30", "2025-03-05", "2025-03-05"]
