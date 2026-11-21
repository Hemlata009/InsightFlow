"""Step 6 tests: missing-value policies, duplicates, key conflicts, quarantine (never delete)."""

import json
from pathlib import Path

import pandas as pd
import pytest

from insightflow.cleaning import REASONS, clean
from insightflow.config import load_dataset_config
from insightflow.ingestion import SOURCE_ROW, read_file
from insightflow.normalization import normalize

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample"
IN = load_dataset_config("SALES_002")

GOOD = {"Order_ID": "O1", "Order_Date": "05/03/2025", "Customer_ID": "C1", "Product": "Pen Set",
        "Category": "Office Supplies", "Region": "North", "Quantity": "2", "Unit_Price": "100",
        "Sales": "180", "Discount": "0.1", "Profit": "20"}


def table(*changes):
    rows = []
    for i, ch in enumerate(changes):
        r = dict(GOOD, Order_ID=f"O{i}")
        r.update(ch)
        rows.append(r)
    df = pd.DataFrame(rows, dtype="string")
    df.insert(0, SOURCE_ROW, range(2, len(rows) + 2))
    return df


def run(df, cfg=IN):
    return clean(normalize(df, cfg), cfg)


def test_clean_rows_pass_through():
    c = run(table({}, {}))
    assert len(c.data) == 2 and c.quarantine.empty and c.duplicates.empty and c.flags == []


def test_unconvertible_value_quarantined_with_reason():
    c = run(table({}, {"Unit_Price": "abc"}))
    assert list(c.quarantine[SOURCE_ROW]) == [3]
    assert c.quarantine.loc[0, REASONS] == "invalid_value:Unit_Price:not_a_number"


def test_missing_required_quarantined():
    c = run(table({"Order_ID": "NA"}, {"Quantity": "-"}))
    assert sorted(c.quarantine[REASONS]) == ["missing_required:Order_ID", "missing_required:Quantity"]


def test_missing_customer_with_nothing_to_copy_is_kept_and_flagged():
    # BR-3: fill from the same order; a one-line order has nothing to copy from -> keep + flag
    c = run(table({"Customer_ID": "NULL"}))
    assert len(c.data) == 1 and pd.isna(c.data.loc[0, "Customer_ID"])
    assert c.flags == [{"stage": "clean", "flag": "missing_value_no_group_value", "source_row": 2,
                        "column": "Customer_ID"}]


@pytest.mark.parametrize("column, expected", [("Discount", 0.1), ("Sales", 180.0), ("Unit_Price", 100.0)])
def test_missing_derived_from_formula(column, expected):
    c = run(table({column: "N/A"}))
    assert c.data.loc[0, column] == pytest.approx(expected)
    assert c.actions[0]["rule"] == "derived" and c.actions[0]["column"] == column


def test_not_derivable_quarantined():
    c = run(table({"Discount": "NA", "Sales": "NA"}))
    assert "missing_not_derivable" in c.quarantine.loc[0, REASONS]


def test_division_by_zero_not_derived():
    c = run(table({"Unit_Price": "NA", "Discount": "1"}))     # Sales / (Q * 0)
    assert "missing_not_derivable:Unit_Price" in c.quarantine.loc[0, REASONS]


def test_exact_and_hidden_duplicates_removed_and_logged():
    df = table({}, {}, {})
    df.loc[1, "Order_ID"] = df.loc[0, "Order_ID"]                       # exact copy of row 2
    df.loc[2, ["Order_ID", "Region", "Product"]] = [df.loc[0, "Order_ID"], " north ", "PEN SET "]
    c = run(df)
    assert len(c.data) == 1
    assert list(c.duplicates[SOURCE_ROW]) == [3, 4] and list(c.duplicates["duplicate_of"]) == [2, 2]
    assert sum(a["rule"] == "duplicate_removed" for a in c.actions) == 2


def test_duplicate_flag_policy_keeps_rows():
    cfg = IN.model_copy(deep=True)
    cfg.duplicates.exact = "flag"
    df = table({}, {})
    df.loc[1, "Order_ID"] = df.loc[0, "Order_ID"]
    c = run(df, cfg)
    assert len(c.data) == 2 and c.flags[0]["flag"] == "exact_duplicate"


def test_key_conflict_flagged_not_removed():
    df = table({}, {"Quantity": "5", "Sales": "450"})
    df.loc[1, "Order_ID"] = df.loc[0, "Order_ID"]                       # same Order+Product, other values
    c = run(df)
    assert len(c.data) == 2 and {f["flag"] for f in c.flags} == {"key_conflict"}


def test_line_items_are_not_duplicates():
    df = table({}, {"Product": "Stapler"})
    df.loc[1, "Order_ID"] = df.loc[0, "Order_ID"]                       # same order, other product
    c = run(df)
    assert len(c.data) == 2 and c.flags == [] and c.duplicates.empty


def test_every_row_is_accounted_for():
    df = table({}, {"Unit_Price": "abc"}, {}, {"Order_ID": "NA"})
    df.loc[2, "Order_ID"] = df.loc[0, "Order_ID"]
    c = run(df)
    assert len(c.data) + len(c.quarantine) + len(c.duplicates) == len(df)


@pytest.mark.parametrize("ds", ["SALES_002", "SALES_001"])
def test_sample_data_cleaning(ds):
    p = SAMPLE / ds / "sales_messy.csv"
    if not p.exists():
        pytest.skip(f"{ds} not built")
    cfg = load_dataset_config(ds)
    raw = read_file(p, known_headers=set(cfg.header_map()))
    key = json.loads((SAMPLE / ds / "answer_key.json").read_text(encoding="utf-8"))
    c = clean(normalize(raw.data, cfg), cfg)
    off = raw.metadata.header_row + 1
    planted = lambda t: {i["messy_row"] + off for i in key["planted_issues"] if i["issue_type"] == t}  # noqa: E731
    assert planted("non_numeric_text") <= set(c.quarantine[SOURCE_ROW])
    assert planted("exact_duplicate") | planted("hidden_duplicate") <= set(c.duplicates[SOURCE_ROW])
    derived = {a["source_row"] for a in c.actions if a["rule"] == "derived"}
    assert {i["messy_row"] + off for i in key["planted_issues"]
            if i["issue_type"] == "null_marker" and i["column"] == "Discount"} <= derived
    assert len(c.data) + len(c.quarantine) + len(c.duplicates) == raw.metadata.rows
