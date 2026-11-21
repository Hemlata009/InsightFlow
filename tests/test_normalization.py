"""Step 5 tests: numbers, dates, text and headers are standardized exactly as the answer key expects."""

import json
from pathlib import Path

import pandas as pd
import pytest

from insightflow.config import load_dataset_config
from insightflow.ingestion import SOURCE_ROW, read_file
from insightflow.normalization import NotConvertible, normalize, parse_dates, parse_number

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample"
IN = load_dataset_config("SALES_002")
US = load_dataset_config("SALES_001")


# ---------------------------------------------------------------- numbers
@pytest.mark.parametrize("text, value", [
    ("1534.2", 1534.2), ("₹1,23,456.00", 123456.0), ("1,00,000", 100000), ("12,34,567.50", 1234567.5),
    ("100,000", 100000), ("6K", 6000), ("1.2345678 L", 123456.78), ("2.5 Cr", 25_000_000),
    ("3 lakh", 300000), ("(1,401.97)", -1401.97), ("₹-500", -500), ("-₹500", -500), ("5%", 0.05),
    ("12.5 %", 0.125), ("INR 500", 500), (" 42 ", 42),
])
def test_parse_number_india(text, value):
    assert parse_number(text, IN.locale)[0] == pytest.approx(value, abs=1e-9)


@pytest.mark.parametrize("text, value", [("$1,234.56", 1234.56), ("1.5342K", 1534.2), ("2.5M", 2.5e6),
                                         ("3 bn", 3e9), ("(250)", -250), ("500 USD", 500)])
def test_parse_number_us(text, value):
    assert parse_number(text, US.locale)[0] == pytest.approx(value)


@pytest.mark.parametrize("locale, text, reason", [
    ("IN", "abc", "not_a_number"), ("IN", "#VALUE!", "not_a_number"), ("IN", "inf", "not_finite"),
    ("IN", "$500", "currency_mismatch"), ("US", "₹500", "currency_mismatch"), ("IN", "USD 5", "currency_mismatch"),
    ("US", "1.2 L", "unknown_suffix"),           # lakh is not a US magnitude
    ("US", "1.234,56", "bad_grouping"), ("IN", "12,3", "bad_grouping"), ("IN", "1.2.3", "bad_grouping"),
])
def test_parse_number_refuses_unsafe(locale, text, reason):
    with pytest.raises(NotConvertible) as e:
        parse_number(text, (IN if locale == "IN" else US).locale)
    assert e.value.reason == reason


# ---------------------------------------------------------------- dates
def _dates(values, cfg):
    d, rule, reason = parse_dates(pd.Series(values, dtype="string"), cfg)
    return [x.date().isoformat() if pd.notna(x) else None for x in d], list(rule), list(reason)


def test_locale_decides_day_month_order():
    assert _dates(["05/03/2025"], IN)[0] == ["2025-03-05"]       # India: 5 March
    assert _dates(["05/03/2015"], US)[0] == ["2015-05-03"]       # US: 3 May


def test_other_date_styles():
    d, rule, _ = _dates(["2025-05-04", "13-Feb-25", "45746", "2025-03-30 10:15:00"], IN)
    assert d == ["2025-05-04", "2025-02-13", "2025-03-30", "2025-03-30"]
    assert rule == ["date_format:%Y-%m-%d", "date_format:%d-%b-%y", "excel_serial", "datetime_time_dropped"]


def test_bad_dates_are_not_guessed():
    d, _, reason = _dates(["31/02/2025", "yesterday", "99999", None], IN)
    assert d == [None, None, None, None]
    assert reason[:3] == ["unrecognised_date"] * 3 and pd.isna(reason[3])


def test_ambiguous_dates_quarantined_when_policy_says_so():
    strict = IN.model_copy(deep=True)
    strict.policies.ambiguous_dates = "quarantine"
    d, _, reason = _dates(["05/03/2025", "25/03/2025"], strict)
    assert d == [None, "2025-03-25"] and reason[0] == "ambiguous_day_month"


# ---------------------------------------------------------------- whole table vs answer key
def run(ds, fname="sales_messy.csv"):
    cfg = load_dataset_config(ds)
    p = SAMPLE / ds / fname
    if not p.exists():
        pytest.skip(f"{ds} not built")
    raw = read_file(p, known_headers=set(cfg.header_map()))
    key = json.loads((SAMPLE / ds / "answer_key.json").read_text(encoding="utf-8"))
    return raw, normalize(raw.data, cfg), key


@pytest.fixture(scope="module", params=["SALES_002", "SALES_001"])
def normalized(request):
    return run(request.param)


def test_headers_become_canonical(normalized):
    _, n, _ = normalized
    assert list(n.data.columns) == [SOURCE_ROW] + list(IN.columns) and n.missing_required == []


def test_types(normalized):
    _, n, _ = normalized
    d = n.data
    assert str(d["Quantity"].dtype) == "Int64" and str(d["Sales"].dtype) == "Float64"
    assert str(d["Order_Date"].dtype).startswith("datetime64") and str(d["Product"].dtype) == "string"


def test_every_normalize_issue_gets_its_true_value(normalized):
    raw, n, key = normalized
    offset = raw.metadata.header_row + 1                      # messy_row 0 = first data line
    by_row = n.data.set_index(SOURCE_ROW)
    truth = pd.read_csv(SAMPLE / key["dataset_id"] / "sales_truth.csv", dtype=str)
    unknowable = 0
    for iss in key["planted_issues"]:
        if iss["expected_action"] != "normalize":
            continue
        if iss["issue_type"] == "whitespace_case":
            got = by_row.loc[iss["messy_row"] + offset, iss["column"]]
            exp = " ".join(iss["expected_value"].split())
            if got != exp and got.casefold() == exp.casefold():
                # The only row with this value: no other spelling to learn the right capitals from.
                assert (truth[iss["column"]] == iss["expected_value"]).sum() == 1, iss
                unknowable += 1
                continue
        got = by_row.loc[iss["messy_row"] + offset, iss["column"]]
        exp = iss["expected_value"]
        if isinstance(got, pd.Timestamp):
            got = got.date().isoformat()
        if isinstance(exp, str):          # truth keeps invisible spaces (U+00A0); we standardize them
            exp = " ".join(exp.split())
        assert got == (pytest.approx(exp, abs=1e-6) if isinstance(exp, float) else exp), iss
    assert unknowable <= 5


def test_unconvertible_values_become_issues(normalized):
    raw, n, key = normalized
    offset = raw.metadata.header_row + 1
    found = {(i["source_row"], i["column"]) for i in n.issues}
    planted = {(i["messy_row"] + offset, i["column"]) for i in key["planted_issues"]
               if i["issue_type"] == "non_numeric_text"}
    assert planted <= found
    assert {i["reason"] for i in n.issues} <= {"not_a_number"}   # nothing else failed


def test_null_markers_become_blank(normalized):
    raw, n, key = normalized
    offset = raw.metadata.header_row + 1
    by_row = n.data.set_index(SOURCE_ROW)
    for iss in key["planted_issues"]:
        if iss["issue_type"] == "null_marker":
            assert pd.isna(by_row.loc[iss["messy_row"] + offset, iss["column"]])


def test_hidden_duplicates_become_exact_after_normalization(normalized):
    raw, n, key = normalized
    offset = raw.metadata.header_row + 1
    by_row = n.data.set_index(SOURCE_ROW)
    for iss in key["planted_issues"]:
        if iss["issue_type"] == "hidden_duplicate":
            r = iss["messy_row"] + offset
            assert by_row.loc[r].equals(by_row.loc[r - 1])


def test_changes_are_logged_with_old_and_new():
    raw, n, _ = run("SALES_002")
    rules = {c["rule"].split(":")[0] for c in n.changes}
    assert {"null_marker", "text_standardized", "number", "date"} <= rules
    c = next(c for c in n.changes if c["rule"] == "number:magnitude_suffix")
    assert c["old"] and isinstance(c["new"], float)


def test_excel_and_csv_normalize_identically():
    _, a, _ = run("SALES_002", "sales_messy.csv")
    _, b, _ = run("SALES_002", "sales_messy.xlsx")
    assert a.data.drop(columns=SOURCE_ROW).reset_index(drop=True).equals(
        b.data.drop(columns=SOURCE_ROW).reset_index(drop=True))


def test_normalizing_twice_changes_nothing():
    raw, n, _ = run("SALES_002")
    again_text = n.data.copy()
    again_text["Order_Date"] = again_text["Order_Date"].dt.strftime("%Y-%m-%d")
    again_text = again_text.astype("string")
    again_text[SOURCE_ROW] = n.data[SOURCE_ROW]
    n2 = normalize(again_text, IN)
    assert n2.data.drop(columns=SOURCE_ROW).equals(n.data.drop(columns=SOURCE_ROW))
    assert [c for c in n2.changes if not c["rule"].startswith("date:")] == []


def test_missing_required_and_extra_columns():
    df = pd.DataFrame({"Qty": ["2"], "colour": ["red"]}, dtype="string")
    n = normalize(df, IN)
    assert "Order_ID" in n.missing_required and "colour" in n.data.columns
    assert any("not in the rule book" in w for w in n.warnings)
