"""Step 4 tests: the health check finds exactly what the answer key planted, and changes nothing."""

import json
from pathlib import Path

import pandas as pd
import pytest

from insightflow.config import load_dataset_config
from insightflow.ingestion import read_file
from insightflow.profiling import classify, profile, summary_text, write_report

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample"


@pytest.mark.parametrize("value, pattern", [
    ("1534.2", "decimal"), ("42", "integer"), ("-999", "integer"),
    ("₹1,23,456.00", "currency"), ("$1,234.56", "currency"), ("INR 500", "currency"), ("500 USD", "currency"),
    ("1,00,000", "grouped_indian"), ("12,34,567.50", "grouped_indian"), ("100,000", "grouped_international"),
    ("1.234,56", "grouped_european"),
    ("6K", "magnitude"), ("1.2345678 L", "magnitude"), ("2.5 Cr", "magnitude"), ("3.1M", "magnitude"),
    ("(1,401.97)", "accounting_negative"), ("5%", "percent"), ("12.5 %", "percent"),
    ("2026-03-05", "date_iso"), ("19/02/2035", "date_slash"), ("13-Feb-25", "date_month_name"),
    ("Mar 5, 2026", "date_month_name"), ("Yes", "boolean"), ("inf", "nan_inf"),
    ("abc", "text"), ("#VALUE!", "text"), ("  ", "empty"),
])
def test_classify(value, pattern):
    assert classify(pd.Series([value]))[0] == pattern


@pytest.fixture(scope="module")
def sales_002():
    cfg = load_dataset_config("SALES_002")
    r = read_file(SAMPLE / "SALES_002" / "sales_messy.csv", known_headers=set(cfg.header_map()))
    key = json.loads((SAMPLE / "SALES_002" / "answer_key.json").read_text(encoding="utf-8"))
    before = r.data.copy()
    rep = profile(r.data, cfg, r.metadata)
    assert r.data.equals(before), "profiling must not change the data"
    by_canon = {c["canonical"]: c for c in rep["columns"].values()}
    return rep, by_canon, key


def planted(key, issue, column=None):
    return sum(1 for i in key["planted_issues"]
               if i["issue_type"] == issue and (column is None or i["column"] == column))


def test_headers_all_mapped(sales_002):
    rep, _, _ = sales_002
    hm = rep["header_mapping"]
    assert len(hm["mapped"]) == 14 and hm["unmapped"] == [] and hm["missing_required"] == []


@pytest.mark.parametrize("column", ["Customer_ID", "Region", "Discount"])
def test_missing_values_match_answer_key(sales_002, column):
    _, cols, key = sales_002
    assert cols[column]["missing"] == planted(key, "null_marker", column)


def test_number_patterns_match_answer_key(sales_002):
    _, cols, key = sales_002
    assert cols["Sales"]["patterns"].get("magnitude", 0) == planted(key, "magnitude_suffix")
    assert cols["Sales"]["patterns"].get("currency", 0) == planted(key, "currency_grouped")
    assert cols["Profit"]["patterns"].get("accounting_negative", 0) == planted(key, "accounting_negative")
    assert cols["Discount"]["patterns"].get("percent", 0) == planted(key, "percent_string")
    assert cols["Unit_Price"]["type_mismatch"] == planted(key, "non_numeric_text")
    assert cols["Discount"]["out_of_range"] == planted(key, "invalid_discount")


def test_date_patterns_match_answer_key(sales_002):
    _, cols, key = sales_002
    d = cols["Order_Date"]
    assert d["patterns"].get("date_iso", 0) == planted(key, "date_iso")
    assert d["patterns"].get("date_month_name", 0) == planted(key, "date_month_name")
    assert d["possible_excel_serial"] == planted(key, "date_excel_serial")
    assert d["slash_dates_outside_date_range"] == planted(key, "date_out_of_range")
    assert d["type_mismatch"] == 0 and d["date_order_used"] == "DMY"
    assert d["ambiguous_day_month"] > 0          # e.g. 05/03/2025: resolved by locale, reported anyway


def test_spelling_and_duplicates_match_answer_key(sales_002):
    rep, cols, key = sales_002
    # whitespace/case planted directly + the hidden duplicate copies (Region and Product changed)
    for column in ["Product", "Region"]:
        expected = planted(key, "whitespace_case", column) + planted(key, "hidden_duplicate")
        assert cols[column]["inconsistent_spelling"] == expected, column
        assert cols[column].get("not_in_allowed_values", 0) == 0
    assert rep["duplicates"]["exact_rows"] == planted(key, "exact_duplicate")
    assert rep["duplicates"]["hidden_duplicates_estimate"] == planted(key, "hidden_duplicate")


def test_findings_and_summary(sales_002):
    rep, _, _ = sales_002
    sev = {f["severity"] for f in rep["findings"]}
    assert {"error", "warning", "info"} <= sev
    text = summary_text(rep)
    assert "SALES_002" in text and "outside the business date range" in text


def test_report_is_json(sales_002, tmp_path):
    rep, _, _ = sales_002
    p = write_report(rep, tmp_path / "profile.json")
    again = json.loads(p.read_text(encoding="utf-8"))
    assert again["rows"] == rep["rows"] and again["source"]["sha256"] == rep["source"]["sha256"]


def test_missing_required_and_unmapped_columns():
    cfg = load_dataset_config("SALES_002")
    df = pd.DataFrame({"Qty": ["1"], "mystery": ["x"]}, dtype="string")
    rep = profile(df, cfg)
    assert rep["header_mapping"]["unmapped"] == ["mystery"]
    assert "Order_ID" in rep["header_mapping"]["missing_required"]


def test_profile_without_config():
    df = pd.DataFrame({"a": ["1", "2", "NA"], "b": ["x", " x", "X"]}, dtype="string")
    rep = profile(df)
    assert rep["columns"]["a"]["missing"] == 1 and rep["columns"]["a"]["dominant_family"] == "numeric"


def test_sales_001_profile():
    p = SAMPLE / "SALES_001" / "sales_messy.csv"
    if not p.exists():
        pytest.skip("SALES_001 not built")
    cfg = load_dataset_config("SALES_001")
    key = json.loads((SAMPLE / "SALES_001" / "answer_key.json").read_text(encoding="utf-8"))
    rep = profile(read_file(p, known_headers=set(cfg.header_map())).data, cfg)
    cols = {c["canonical"]: c for c in rep["columns"].values()}
    assert cols["Order_Date"]["date_order_used"] == "MDY"
    assert cols["Order_Date"]["slash_dates_outside_date_range"] == planted(key, "date_out_of_range")
    assert cols["Quantity"]["out_of_range"] >= planted(key, "invalid_quantity")      # -999 < min 1
    assert rep["duplicates"]["exact_rows"] >= planted(key, "exact_duplicate")
