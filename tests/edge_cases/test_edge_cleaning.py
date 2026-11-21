"""Edge-case group 4: missing values, imputation, groups, booleans, optional columns."""

from pathlib import Path

import pandas as pd
import pytest
from pydantic import ValidationError

from insightflow.cleaning import REASONS, clean
from insightflow.config import ColumnSpec, load_dataset_config
from insightflow.ingestion import SOURCE_ROW
from insightflow.normalization import normalize
from insightflow.pipeline import run_phase1

IN = load_dataset_config("SALES_002")
BASE = {"Order_ID": "O1", "Order_Date": "05/03/2025", "Customer_ID": "C1", "Product": "Pen Set",
        "Category": "Office Supplies", "Region": "North", "Quantity": "2", "Unit_Price": "100",
        "Sales": "180", "Discount": "0.1", "Profit": "20", "State": "Delhi"}
PRODUCTS = ["Pen Set", "Stapler", "Paper Ream", "Notebook Pack", "Desk Organizer", "Laptop", "Monitor"]


def table(rows):
    out = []
    for i, ch in enumerate(rows):
        r = dict(BASE, Product=PRODUCTS[i % len(PRODUCTS)])
        r.update(ch)
        out.append(r)
    df = pd.DataFrame(out, dtype="string")
    df.insert(0, SOURCE_ROW, range(2, len(out) + 2))
    return df


def with_policy(col, **spec):
    c = IN.model_copy(deep=True)
    c.columns[col] = c.columns[col].model_copy(update=spec)
    return c


def cleaned(rows, cfg):
    return clean(normalize(table(rows), cfg), cfg)


# ---------------- fill from the same group (never across groups)
def test_fill_customer_from_other_lines_of_the_same_order():
    cfg = with_policy("Customer_ID", missing_policy="fill_from_group", group_by=["Order_ID"])
    c = cleaned([{"Customer_ID": "C7"}, {"Customer_ID": "NA"},
                 {"Order_ID": "O2", "Customer_ID": "C9"}], cfg)
    assert list(c.data["Customer_ID"]) == ["C7", "C7", "C9"]          # O1's blank got O1's customer, not O2's
    assert [a["rule"] for a in c.actions] == ["filled_from_group"]


def test_fill_from_group_refuses_when_the_group_disagrees():
    cfg = with_policy("Customer_ID", missing_policy="fill_from_group", group_by=["Order_ID"])
    c = cleaned([{"Customer_ID": "C7"}, {"Customer_ID": "C8"}, {"Customer_ID": "-"}], cfg)
    # Customer may be blank: nothing is copied (never guess) and the row is kept blank + flagged
    assert c.quarantine.empty and pd.isna(c.data["Customer_ID"].iloc[2])
    assert {f["flag"] for f in c.flags} == {"group_values_conflict"}


def test_group_conflict_on_a_required_column_sets_the_row_aside():
    cfg = with_policy("Order_Date", missing_policy="fill_from_group", group_by=["Order_ID"], nullable=False)
    c = cleaned([{"Order_Date": "05/03/2025"}, {"Order_Date": "06/03/2025"}, {"Order_Date": ""}], cfg)
    assert c.quarantine.loc[0, REASONS] == "group_values_conflict:Order_Date"


def test_invalid_value_replaced_from_the_group():
    c = cleaned([{"Region": "North"}, {"Region": "Mars"}], IN)                     # same State (Delhi): BR-2
    assert c.data["Region"].tolist() == ["North", "North"]
    assert any(f["flag"] == "invalid_value_replaced" for f in c.flags)


def test_fill_from_group_with_no_value_in_group_is_flagged():
    cfg = with_policy("Customer_ID", missing_policy="fill_from_group", group_by=["Order_ID"])
    c = cleaned([{"Order_ID": "O5", "Customer_ID": "NA"}, {"Order_ID": "NA", "Customer_ID": "NA"}], cfg)
    assert "missing_value_no_group_value" in {f["flag"] for f in c.flags}


def test_fill_order_date_from_the_order():
    cfg = with_policy("Order_Date", missing_policy="fill_from_group", group_by=["Order_ID"], nullable=True)
    c = cleaned([{"Order_Date": "07/03/2025"}, {"Order_Date": ""}], cfg)
    assert list(c.data["Order_Date"].dt.strftime("%Y-%m-%d")) == ["2025-03-07", "2025-03-07"]


# ---------------- statistical imputation (guarded and logged)
def test_median_imputation_is_logged_with_distribution():
    cfg = with_policy("Profit", missing_policy="impute", impute_method="median")
    c = cleaned([{"Profit": "10"}, {"Profit": "20"}, {"Profit": "30"}, {"Profit": "NA"}], cfg)
    assert c.data["Profit"].tolist()[-1] == 20
    a = c.actions[0]
    assert a["rule"] == "imputed_median" and "before" in a["detail"] and "after" in a["detail"]


def test_mean_imputation_refused_on_skewed_data():
    cfg = with_policy("Profit", missing_policy="impute", impute_method="mean")
    rows = [{"Profit": v} for v in ["1", "1", "2", "1", "2", "1", "5000"]] + [{"Profit": "NA"}]
    c = cleaned(rows, cfg)
    assert pd.isna(c.data["Profit"].iloc[-1])                           # not filled with ~715
    assert c.flags[0]["flag"] == "imputation_skipped_skewed"


def test_mean_imputation_on_symmetric_data():
    cfg = with_policy("Profit", missing_policy="impute", impute_method="mean")
    c = cleaned([{"Profit": "10"}, {"Profit": "20"}, {"Profit": "30"}, {"Profit": "-"}], cfg)
    assert c.data["Profit"].iloc[-1] == pytest.approx(20)


def test_mode_imputation_for_text():
    cfg = with_policy("Region", missing_policy="impute", impute_method="mode")
    c = cleaned([{"Region": "North"}, {"Region": "North"}, {"Region": "South"}, {"Region": "NA"}], cfg)
    assert c.data["Region"].iloc[-1] == "North"


@pytest.mark.parametrize("spec, msg", [
    ({"type": "string", "missing_policy": "impute", "impute_method": "median"}, "only applies to numeric"),
    ({"type": "float", "missing_policy": "impute"}, "needs impute_method"),
    ({"type": "string", "missing_policy": "fill_from_group"}, "needs group_by"),
])
def test_bad_imputation_configs_rejected(spec, msg):
    with pytest.raises(ValidationError, match=msg):
        ColumnSpec.model_validate({"name": "x", **spec})


# ---------------- meaningful missing: zero vs unknown
def test_missing_discount_can_mean_zero_when_the_business_says_so():
    cfg = with_policy("Discount", missing_policy="fill_value", fill_value=0)
    c = cleaned([{"Discount": "", "Sales": "200"}], cfg)
    assert c.data["Discount"].iloc[0] == 0 and c.actions[0]["rule"] == "fill_value"


# ---------------- booleans
def test_boolean_column():
    cfg = IN.model_copy(deep=True)
    cfg.columns["Paid"] = ColumnSpec(name="Paid", type="boolean", aliases=["paid", "is_paid"])
    df = table([{}, {}, {}, {}, {}])
    df["Is Paid"] = pd.array(["Yes", "n", "TRUE", "0", "maybe"], dtype="string")
    n = normalize(df, cfg)
    assert n.data["Paid"].tolist()[:4] == [True, False, True, False]
    assert n.issues[0]["reason"] == "not_a_boolean"


# ---------------- optional columns may be absent
def test_file_without_optional_columns_runs(tmp_path):
    header = ",".join(BASE)
    p = tmp_path / "min.csv"
    p.write_text(header + "\n" + ",".join(BASE.values()) + "\n", encoding="utf-8")
    res = run_phase1(p, "SALES_002", data_root=tmp_path / "data")
    assert res["status"] == "completed" and res["rows_output"] == 1


def test_imputation_changes_nothing_when_nothing_is_missing():
    cfg = with_policy("Profit", missing_policy="impute", impute_method="median")
    c = cleaned([{"Profit": "10"}, {"Profit": "20"}], cfg)
    assert c.actions == [] and c.flags == []
